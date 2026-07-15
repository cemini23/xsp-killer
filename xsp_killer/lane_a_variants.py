"""Lane A variant soak — parallel paper instances with different entry/exit params."""

from __future__ import annotations

import json
import logging
import math
import shutil
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from xsp_killer.fs_lock import flock_un, open_ex_lock
from xsp_killer.lane_a_entry import (
    DEFAULT_TELEMETRY_BRIEF,
    _sync_entry_telemetry,
    _write_entry_telemetry_brief,
    et_session_date,
    is_et_trading_session,
    run_paper_entry,
    scoreboard_entry_stale,
    summarize_entry_telemetry_from_logs,
    unique_et_sessions,
)
from xsp_killer.lane_a_monitor import (
    DEFAULT_PAPER_BRIEF,
    DEFAULT_RULES,
    compute_paper_open_mtm,
    load_state,
    run_monitor,
    save_state,
    write_paper_pnl_brief,
)
from xsp_killer.paper_economics import load_premium_scale

logger = logging.getLogger("xsp_killer.lane_a_variants")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VARIANTS_CONFIG = ROOT / "config" / "lane_a_variants.yaml"
DEFAULT_VARIANTS_STATE = ROOT / "briefs" / "xsp-lane-a-variants-state.json"
DEFAULT_BASELINE_STATE = ROOT / "briefs" / "xsp-lane-a-state.json"
DEFAULT_SCOREBOARD = ROOT / "briefs" / "xsp-lane-a-variants-scoreboard.json"

# Side-by-side regime-gate experiment axis (baseline GREEN vs YELLOW bounce brackets).
REGIME_GATE_COMPARISON_IDS = (
    "v2_baseline_prod",
    "v2_yellow_mid_bounce",
    "v2_yellow_top_quartile_bounce",
)

PROMOTION_SESSIONS_GATE = 20
PROMOTION_ENTERED_SESSIONS_GATE = 10
PROMOTION_TRADES_GATE = 20


@dataclass
class VariantSpec:
    variant_id: str
    description: str
    active: bool
    overrides: dict[str, Any]

    @property
    def logic_version(self) -> str:
        logging_cfg = self.overrides.get("logging") or {}
        return str(logging_cfg.get("logic_version") or f"xsp_lane_a_{self.variant_id}")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_base_rules() -> dict[str, Any]:
    return yaml.safe_load(DEFAULT_RULES.read_text(encoding="utf-8")) or {}


def load_variant_specs(path: Path | None = None) -> list[VariantSpec]:
    cfg_path = path or DEFAULT_VARIANTS_CONFIG
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    specs: list[VariantSpec] = []
    for variant_id, raw in (data.get("variants") or {}).items():
        if not isinstance(raw, dict):
            continue
        specs.append(
            VariantSpec(
                variant_id=str(variant_id),
                description=str(raw.get("description") or ""),
                active=bool(raw.get("active", True)),
                overrides=dict(raw.get("overrides") or {}),
            )
        )
    return specs


def merged_rules_path(spec: VariantSpec, *, tmp_dir: Path | None = None) -> Path:
    merged = _deep_merge(load_base_rules(), spec.overrides)
    out_dir = tmp_dir or (ROOT / "briefs" / "variant_rules_cache")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{spec.variant_id}.yaml"
    out_path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    return out_path


def load_variants_state(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_VARIANTS_STATE
    if not p.is_file():
        return {"variants": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"variants": {}}


def variant_state_slice(root: dict[str, Any], variant_id: str) -> dict[str, Any]:
    variants = root.setdefault("variants", {})
    if variant_id not in variants or not isinstance(variants[variant_id], dict):
        variants[variant_id] = {
            "paper_positions": {},
            "entry_log": [],
            "paper_events": [],
            "positions": {},
        }
    return variants[variant_id]


def _variants_state_lock(path: Path):
    return open_ex_lock(path)


def _write_variants_state(root: dict[str, Any], path: Path | None = None) -> Path:
    p = path or DEFAULT_VARIANTS_STATE
    lock = _variants_state_lock(p)
    try:
        p.write_text(json.dumps(root, indent=2) + "\n", encoding="utf-8")
    finally:
        flock_un(lock)
        lock.close()
    return p


@contextmanager
def _variants_rmw_lock(path: Path | None = None):
    """Best-effort exclusive lock around a load→run→save cycle on the shared
    variants state file. Guards against the intraday/entry/monitor timers
    colliding on the same variants_state.json. Non-fatal if flock is
    unavailable (e.g. unsupported filesystem): the cycle proceeds unlocked."""
    p = path or DEFAULT_VARIANTS_STATE
    lockfile = p.with_name(p.name + ".lock")
    fh = None
    try:
        fh = _variants_state_lock(lockfile)
    except Exception as exc:  # noqa: BLE001 — best-effort lock
        logger.warning("variants RMW lock unavailable, proceeding unlocked: %s", exc)
        fh = None
    try:
        yield
    finally:
        if fh is not None:
            try:
                flock_un(fh)
                fh.close()
            except Exception:  # noqa: BLE001 — best-effort release
                pass


def _baseline_brief_path(baseline_state_path: Path, default_path: Path) -> Path:
    if baseline_state_path == DEFAULT_BASELINE_STATE:
        return default_path
    return baseline_state_path.with_name(default_path.name)


def save_variant_state_slice(
    root: dict[str, Any],
    variant_id: str,
    slice_state: dict[str, Any],
    *,
    path: Path | None = None,
) -> None:
    root.setdefault("variants", {})[variant_id] = slice_state
    _write_variants_state(root, path)


def ensure_variant_slices(
    root: dict[str, Any], specs: list[VariantSpec] | tuple[VariantSpec, ...]
) -> list[str]:
    created: list[str] = []
    for spec in specs:
        if not spec.active:
            continue
        variants = root.setdefault("variants", {})
        if spec.variant_id not in variants or not isinstance(
            variants[spec.variant_id], dict
        ):
            variant_state_slice(root, spec.variant_id)
            created.append(spec.variant_id)
    return created


def _variant_intraday_enabled(spec: VariantSpec) -> bool:
    """True when the variant's merged rules enable intraday BB-bounce entries."""
    from xsp_killer.lane_a_ta import TaRules

    try:
        return TaRules.from_yaml(merged_rules_path(spec)).intraday_entry_enabled
    except Exception:
        return False


def run_variant_entry(
    spec: VariantSpec,
    *,
    root_state: dict[str, Any] | None = None,
    state_path: Path | None = None,
    now_et: datetime | None = None,
    force: bool = False,
    intraday: bool = False,
) -> Any:
    root = root_state if root_state is not None else load_variants_state(state_path)
    slice_state = variant_state_slice(root, spec.variant_id)
    rules_path = merged_rules_path(spec)
    log_path = ROOT / "logs" / f"xsp_lane_a_variant_{spec.variant_id}.jsonl"
    tmp_state = ROOT / "briefs" / f".variant-{spec.variant_id}-state.json"
    save_state(tmp_state, slice_state)

    decision = run_paper_entry(
        rules_path=rules_path,
        state_path=tmp_state,
        log_path=log_path,
        now_et=now_et,
        force=force,
        intraday=intraday,
        publish_intel=False,
        brief_path=False,
    )
    updated = load_state(tmp_state)
    if decision.entered and decision.position:
        pos = dict(decision.position)
        pos["variant_id"] = spec.variant_id
        updated.setdefault("paper_positions", {})[pos["position_id"]] = pos
    save_variant_state_slice(root, spec.variant_id, updated, path=state_path)
    try:
        tmp_state.unlink(missing_ok=True)
    except OSError:
        pass
    return decision


def run_variant_monitor(
    spec: VariantSpec,
    *,
    root_state: dict[str, Any] | None = None,
    state_path: Path | None = None,
    now_et: datetime | None = None,
) -> Any:
    root = root_state if root_state is not None else load_variants_state(state_path)
    slice_state = variant_state_slice(root, spec.variant_id)
    rules_path = merged_rules_path(spec)
    tmp_state = ROOT / "briefs" / f".variant-{spec.variant_id}-state.json"
    save_state(tmp_state, slice_state)
    log_path = ROOT / "logs" / f"xsp_lane_a_variant_{spec.variant_id}.jsonl"

    report = run_monitor(
        rules_path=rules_path,
        state_path=tmp_state,
        now_et=now_et,
        publish_intel=False,
        log_path=log_path,
        write_paper_brief=False,
    )
    updated = load_state(tmp_state)
    save_variant_state_slice(root, spec.variant_id, updated, path=state_path)
    try:
        tmp_state.unlink(missing_ok=True)
    except OSError:
        pass
    return report


def _prune_variant_rules_cache(active_ids: set[str]) -> None:
    cache_dir = ROOT / "briefs" / "variant_rules_cache"
    if not cache_dir.is_dir():
        return
    for fp in cache_dir.glob("*.yaml"):
        if fp.stem not in active_ids:
            try:
                fp.unlink(missing_ok=True)
            except OSError:
                pass


def run_all_variant_entries(
    *,
    config_path: Path | None = None,
    state_path: Path | None = None,
    now_et: datetime | None = None,
    exclude: set[str] | None = None,
    force: bool = False,
    intraday: bool = False,
    intraday_only: bool = False,
) -> list[tuple[VariantSpec, Any]]:
    from xsp_killer.chain_cache import clear_chain_cache

    specs = load_variant_specs(config_path)
    _prune_variant_rules_cache({s.variant_id for s in specs if s.active})
    clear_chain_cache()
    with _variants_rmw_lock(state_path):
        root = load_variants_state(state_path)
        created = ensure_variant_slices(root, specs)
        if created:
            _write_variants_state(root, state_path)
        results: list[tuple[VariantSpec, Any]] = []
        for spec in specs:
            if not spec.active:
                continue
            if exclude and spec.variant_id in exclude:
                continue
            # Intraday passes only run variants that opt into intraday entries
            # (dip-bounce swings); close-window variants are left to the 15:45 run.
            if intraday_only and not _variant_intraday_enabled(spec):
                continue
            try:
                decision = run_variant_entry(
                    spec,
                    root_state=root,
                    state_path=state_path,
                    now_et=now_et,
                    force=force,
                    intraday=intraday,
                )
                results.append((spec, decision))
                logger.info(
                    "variant_entry %s entered=%s reason=%s",
                    spec.variant_id,
                    decision.entered,
                    decision.skip_reason,
                )
            except Exception as exc:
                logger.exception("variant_entry %s failed: %s", spec.variant_id, exc)
    return results


def run_all_variant_monitors(
    *,
    config_path: Path | None = None,
    state_path: Path | None = None,
    now_et: datetime | None = None,
    exclude: set[str] | None = None,
    intraday_only: bool = False,
) -> list[tuple[VariantSpec, Any]]:
    from xsp_killer.chain_cache import clear_chain_cache

    specs = load_variant_specs(config_path)
    clear_chain_cache()
    with _variants_rmw_lock(state_path):
        root = load_variants_state(state_path)
        created = ensure_variant_slices(root, specs)
        if created:
            _write_variants_state(root, state_path)
        results: list[tuple[VariantSpec, Any]] = []
        for spec in specs:
            if not spec.active:
                continue
            if exclude and spec.variant_id in exclude:
                continue
            # Intraday passes only monitor variants that hold across days
            # (swing/dip-bounce); close-window variants exit in the morning run.
            if intraday_only and not _variant_intraday_enabled(spec):
                continue
            try:
                report = run_variant_monitor(
                    spec, root_state=root, state_path=state_path, now_et=now_et
                )
                results.append((spec, report))
                logger.info(
                    "variant_monitor %s positions=%d alerts=%d",
                    spec.variant_id,
                    len(report.positions),
                    len(report.alerts),
                )
            except Exception as exc:
                logger.exception("variant_monitor %s failed: %s", spec.variant_id, exc)
    return results


def _soak_reset_at(root: dict[str, Any]) -> str | None:
    raw = root.get("soak_reset_at")
    return str(raw) if raw else None


def _events_in_soak_epoch(
    state: dict[str, Any], soak_reset_at: str | None
) -> list[dict[str, Any]]:
    events = [e for e in (state.get("paper_events") or []) if isinstance(e, dict)]
    if not soak_reset_at:
        return events
    return [e for e in events if str(e.get("evaluated_at") or "") >= soak_reset_at]


def _entry_logs_in_soak_epoch(
    state: dict[str, Any], soak_reset_at: str | None
) -> list[dict[str, Any]]:
    logs = [e for e in (state.get("entry_log") or []) if isinstance(e, dict)]
    if not soak_reset_at:
        return logs
    return [e for e in logs if str(e.get("evaluated_at") or "") >= soak_reset_at]


def _parse_timestamp(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _last_exit_with_contract_meta(
    state: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if not events:
        return None
    last_exit = dict(events[-1])
    paper_positions = state.get("paper_positions") or {}
    position = (
        paper_positions.get(last_exit.get("position_id"))
        if isinstance(paper_positions, dict)
        else None
    )
    if not isinstance(position, dict):
        position = {}

    dte_actual = last_exit.get("dte_actual", position.get("dte_actual"))
    if dte_actual is not None:
        last_exit["dte_actual"] = dte_actual

    expiration = (
        last_exit.get("expiration")
        or last_exit.get("expiration_date")
        or position.get("expiration")
        or position.get("expiration_date")
    )
    if expiration is not None:
        last_exit["expiration"] = expiration

    for field in ("chain_symbol", "option_type", "strike"):
        value = last_exit.get(field, position.get(field))
        if value is not None:
            last_exit[field] = value

    return last_exit


def reset_soak(
    *,
    commit: str | None = None,
    reason: str = "post-patch scoreboard epoch",
    state_path: Path | None = None,
    baseline_state_path: Path | None = None,
    scoreboard_path: Path | None = None,
    archive_dir: Path | None = None,
    clear_baseline_events: bool = True,
) -> dict[str, Any]:
    """Archive pre-reset soak data and start a fresh scoreboard epoch."""
    reset_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sp = state_path or DEFAULT_VARIANTS_STATE
    bp = baseline_state_path or (ROOT / "briefs" / "xsp-lane-a-state.json")
    sb = scoreboard_path or DEFAULT_SCOREBOARD
    ad = archive_dir or (ROOT / "briefs" / "archive")
    ad.mkdir(parents=True, exist_ok=True)
    stamp = reset_at.replace(":", "").replace("-", "")[:15]

    archived: list[str] = []
    for src in (sp, sb, bp):
        if src.is_file():
            dest = ad / f"{src.stem}-pre-reset-{stamp}{src.suffix}"
            shutil.copy2(src, dest)
            archived.append(str(dest))

    root = load_variants_state(sp)
    for slice_state in (root.get("variants") or {}).values():
        if isinstance(slice_state, dict):
            slice_state["paper_events"] = []
            slice_state["entry_log"] = []

    root["soak_reset_at"] = reset_at
    root["pnl_epoch_at"] = reset_at
    if commit:
        root["soak_reset_commit"] = commit
        root["pnl_epoch_commit"] = commit
    root["soak_reset_reason"] = reason
    root["soak_reset_archives"] = archived

    _write_variants_state(root, sp)

    if clear_baseline_events and bp.is_file():
        try:
            baseline = json.loads(bp.read_text(encoding="utf-8"))
            baseline["paper_events"] = []
            baseline["soak_reset_at"] = reset_at
            baseline["pnl_epoch_at"] = reset_at
            if commit:
                baseline["soak_reset_commit"] = commit
                baseline["pnl_epoch_commit"] = commit
            _sync_entry_telemetry(baseline)
            bp.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
            _write_entry_telemetry_brief(
                baseline,
                out_path=_baseline_brief_path(bp, DEFAULT_TELEMETRY_BRIEF),
            )
            write_paper_pnl_brief(
                baseline,
                out_path=_baseline_brief_path(bp, DEFAULT_PAPER_BRIEF),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("baseline soak reset failed: %s", exc)

    out = build_scoreboard(state_path=sp, baseline_state_path=bp, out_path=sb)
    meta = {
        "soak_reset_at": reset_at,
        "soak_reset_commit": commit,
        "soak_reset_reason": reason,
        "archived": archived,
        "scoreboard": str(out),
    }
    logger.info("variant soak reset: %s", meta)
    return meta


def clear_pnl_epoch(
    *,
    commit: str | None = None,
    reason: str = "unreliable PnL cleared — per-variant epoch restart",
    state_path: Path | None = None,
    baseline_state_path: Path | None = None,
    scoreboard_path: Path | None = None,
    archive_dir: Path | None = None,
) -> dict[str, Any]:
    """Clear paper_events only; keep entry history. Restart per-variant PnL tracking."""
    epoch_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sp = state_path or DEFAULT_VARIANTS_STATE
    bp = baseline_state_path or (ROOT / "briefs" / "xsp-lane-a-state.json")
    sb = scoreboard_path or DEFAULT_SCOREBOARD
    ad = archive_dir or (ROOT / "briefs" / "archive")
    ad.mkdir(parents=True, exist_ok=True)
    stamp = epoch_at.replace(":", "").replace("-", "")[:15]

    archived: list[str] = []
    for src in (sp, sb, bp):
        if src.is_file():
            dest = ad / f"{src.stem}-pre-pnl-clear-{stamp}{src.suffix}"
            shutil.copy2(src, dest)
            archived.append(str(dest))

    root = load_variants_state(sp)
    for slice_state in (root.get("variants") or {}).values():
        if isinstance(slice_state, dict):
            slice_state["paper_events"] = []

    root["soak_reset_at"] = epoch_at
    root["pnl_epoch_at"] = epoch_at
    if commit:
        root["pnl_epoch_commit"] = commit
    root["pnl_clear_reason"] = reason
    root["pnl_clear_archives"] = archived

    _write_variants_state(root, sp)

    if bp.is_file():
        try:
            baseline = json.loads(bp.read_text(encoding="utf-8"))
            baseline["paper_events"] = []
            baseline["soak_reset_at"] = epoch_at
            baseline["pnl_epoch_at"] = epoch_at
            if commit:
                baseline["pnl_epoch_commit"] = commit
            _sync_entry_telemetry(baseline)
            bp.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
            _write_entry_telemetry_brief(
                baseline,
                out_path=_baseline_brief_path(bp, DEFAULT_TELEMETRY_BRIEF),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("baseline pnl clear failed: %s", exc)

    out = build_scoreboard(state_path=sp, baseline_state_path=bp, out_path=sb)
    return {
        "pnl_epoch_at": epoch_at,
        "pnl_epoch_commit": commit,
        "pnl_clear_reason": reason,
        "archived": archived,
        "scoreboard": str(out),
    }


def resync_epoch_briefs_if_needed(
    *,
    state_path: Path | None = None,
    baseline_state_path: Path | None = None,
    scoreboard_path: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Idempotent epoch resync when scoreboard/brief parity is broken."""
    from xsp_killer.health_soak import brief_consistency_anomalies

    sb = scoreboard_path or DEFAULT_SCOREBOARD
    bp = baseline_state_path or DEFAULT_BASELINE_STATE
    telemetry_path = _baseline_brief_path(bp, DEFAULT_TELEMETRY_BRIEF)
    paper_path = _baseline_brief_path(bp, DEFAULT_PAPER_BRIEF)

    out = build_scoreboard(
        config_path=config_path,
        state_path=state_path,
        baseline_state_path=bp,
        out_path=sb,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    paper_brief = None
    telemetry_brief = None
    if paper_path.is_file():
        try:
            paper_brief = json.loads(paper_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            paper_brief = None
    if telemetry_path.is_file():
        try:
            telemetry_brief = json.loads(telemetry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            telemetry_brief = None

    anomalies = brief_consistency_anomalies(
        payload,
        paper_brief=paper_brief,
        telemetry_brief=telemetry_brief,
    )
    if "pnl_epoch_mismatch" not in anomalies:
        return {"synced": False, "reason": "parity_ok", "scoreboard": str(out)}

    meta = resync_epoch_briefs(
        state_path=state_path,
        baseline_state_path=bp,
        scoreboard_path=sb,
        config_path=config_path,
    )
    meta["synced"] = True
    meta["reason"] = "pnl_epoch_mismatch"
    return meta


def resync_epoch_briefs(
    *,
    state_path: Path | None = None,
    baseline_state_path: Path | None = None,
    scoreboard_path: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Restore baseline brief epoch parity from variants-state canonical pnl_epoch_at."""
    sp = state_path or DEFAULT_VARIANTS_STATE
    bp = baseline_state_path or DEFAULT_BASELINE_STATE
    sb = scoreboard_path or DEFAULT_SCOREBOARD

    root = load_variants_state(sp)
    canonical_epoch = root.get("pnl_epoch_at")
    if bp.is_file():
        try:
            baseline = json.loads(bp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            baseline = {}
    else:
        baseline = {}

    baseline["pnl_epoch_at"] = canonical_epoch
    _sync_entry_telemetry(baseline)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    telemetry_path = _baseline_brief_path(bp, DEFAULT_TELEMETRY_BRIEF)
    paper_path = _baseline_brief_path(bp, DEFAULT_PAPER_BRIEF)
    _write_entry_telemetry_brief(baseline, out_path=telemetry_path)
    write_paper_pnl_brief(baseline, out_path=paper_path)
    out = build_scoreboard(
        config_path=config_path,
        state_path=sp,
        baseline_state_path=bp,
        out_path=sb,
    )
    return {
        "pnl_epoch_at": canonical_epoch,
        "baseline_state": str(bp),
        "telemetry_brief": str(telemetry_path),
        "paper_brief": str(paper_path),
        "scoreboard": str(out),
    }


def _variant_track_meta(
    variant_id: str,
    spec: VariantSpec | None,
) -> dict[str, Any]:
    """Regime-gate metadata for scoreboard rows and cross-variant comparison."""
    if spec is not None:
        entry = spec.overrides.get("entry") or {}
        logic_version = spec.logic_version
    elif variant_id == "v2_baseline_prod":
        base = load_base_rules()
        entry = base.get("entry") or {}
        logic_version = str((base.get("logging") or {}).get("logic_version") or "")
    else:
        entry = {}
        logic_version = None

    regime_gate = str(entry.get("regime_gate") or "GREEN")
    yellow_frac_min = entry.get("regime_yellow_frac_min")

    meta: dict[str, Any] = {
        "logic_version": logic_version,
        "regime_gate": regime_gate,
        "regime_yellow_frac_min": yellow_frac_min,
    }
    if regime_gate == "GREEN_OR_YELLOW_BOUNCE":
        meta["track_family"] = "yellow_bounce_frac_axis"
    elif regime_gate == "GREEN" and variant_id == "v2_baseline_prod":
        meta["track_family"] = "baseline_green"
    return meta


def _entry_session_stats(entry_logs: list[dict[str, Any]]) -> dict[str, int]:
    sessions = _entry_session_rows(entry_logs)
    entered_sessions = sum(
        1 for rows in sessions if any(row.get("entered") for row in rows)
    )
    regime_gate_skips = sum(
        1
        for rows in sessions
        if not any(row.get("entered") for row in rows)
        and str(_session_outcome_row(rows).get("skip_reason") or "").startswith(
            "regime "
        )
    )
    bounce_signal_sessions = sum(
        1 for rows in sessions if any(row.get("bb_entry_ok") for row in rows)
    )
    bounce_blocked_by_regime = sum(
        1
        for rows in sessions
        if any(row.get("bb_entry_ok") for row in rows)
        and not any(row.get("entered") for row in rows)
        and str(_session_outcome_row(rows).get("skip_reason") or "").startswith(
            "regime "
        )
    )
    return {
        "entered_sessions": entered_sessions,
        "regime_gate_skip_sessions": regime_gate_skips,
        "bb_bounce_signal_sessions": bounce_signal_sessions,
        "bb_bounce_blocked_by_regime_sessions": bounce_blocked_by_regime,
    }


def _vol_shadow_from_log_row(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("vol_shadow")
    if isinstance(raw, dict):
        return raw
    if (
        row.get("spy_rv_annualized") is not None
        or row.get("vol_shadow_would_block") is not None
    ):
        return {
            "spy_rv_annualized": row.get("spy_rv_annualized"),
            "shadow_would_block": row.get("vol_shadow_would_block"),
            "reason": row.get("vol_shadow_reason"),
        }
    return None


def _vol_shadow_session_stats(entry_logs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate shadow vol gate observations from epoch entry_log rows."""
    would_block_sessions = 0
    halve_sessions = 0
    rvs: list[float] = []
    latest: dict[str, Any] | None = None
    for row in entry_logs:
        vs = _vol_shadow_from_log_row(row)
        if vs is None:
            continue
        latest = vs
        if vs.get("shadow_would_block"):
            would_block_sessions += 1
        if vs.get("shadow_would_halve_size"):
            halve_sessions += 1
        rv = vs.get("spy_rv_annualized")
        if rv is not None:
            try:
                rvs.append(float(rv))
            except (TypeError, ValueError):
                pass
    return {
        "vol_shadow_would_block_sessions": would_block_sessions,
        "vol_shadow_halve_size_sessions": halve_sessions,
        "vol_shadow_latest_spy_rv": (latest or {}).get("spy_rv_annualized"),
        "vol_shadow_latest_would_block": (latest or {}).get("shadow_would_block"),
        "vol_shadow_latest_vix_spike_ratio": (latest or {}).get("vix_spike_ratio"),
        "vol_shadow_latest_halve_size": (latest or {}).get("shadow_would_halve_size"),
        "vol_shadow_avg_spy_rv": round(sum(rvs) / len(rvs), 4) if rvs else None,
    }


def _entry_session_rows(entry_logs: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in entry_logs:
        session = et_session_date(row.get("evaluated_at"))
        if not session:
            continue
        try:
            if not is_et_trading_session(date.fromisoformat(session)):
                continue
        except ValueError:
            continue
        grouped.setdefault(session, []).append(row)
    return [grouped[key] for key in sorted(grouped)]


def _session_outcome_row(session_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(session_rows, key=lambda row: str(row.get("evaluated_at") or ""))
    entered = next((row for row in ordered if row.get("entered")), None)
    return entered or ordered[-1]


def _weekend_eval_count(entry_logs: list[dict[str, Any]]) -> int:
    count = 0
    for row in entry_logs:
        session = et_session_date(row.get("evaluated_at"))
        if not session:
            continue
        try:
            if not is_et_trading_session(date.fromisoformat(session)):
                count += 1
        except ValueError:
            continue
    return count


def _open_positions_metrics(
    state: dict[str, Any],
    *,
    rules_path: Path | None = None,
) -> dict[str, float]:
    mtm_scaled, mtm_1x = compute_paper_open_mtm(state, rules_path=rules_path)
    return {
        "open_positions_mtm_usd": mtm_scaled,
        "open_positions_mtm_usd_1x": mtm_1x,
    }


def _contract_key(raw: dict[str, Any]) -> str | None:
    expiration = raw.get("expiration_date") or raw.get("expiration")
    strike = raw.get("strike")
    position_id = str(raw.get("position_id") or "")
    chain_symbol = str(raw.get("chain_symbol") or "XSP").upper()
    option_type = str(raw.get("option_type") or "call").lower()
    if (expiration is None or strike is None) and position_id.startswith("paper:"):
        parts = position_id.split(":")
        if len(parts) >= 4:
            chain_symbol = str(parts[1] or chain_symbol).upper()
            if expiration is None:
                expiration = parts[2]
            if strike is None:
                strike = parts[3]
    if expiration is None or strike is None:
        return None
    try:
        strike_val = float(strike)
    except (TypeError, ValueError):
        return None
    if strike_val.is_integer():
        strike_part = str(int(strike_val))
    else:
        strike_part = str(strike_val)
    return f"{chain_symbol}:{option_type}:{expiration}:{strike_part}"


def _contract_cluster_id(
    *,
    open_positions: list[dict[str, Any]],
    last_exit: dict[str, Any] | None,
) -> str | None:
    keys = sorted(
        {
            key
            for pos in open_positions
            if isinstance(pos, dict)
            for key in [_contract_key(pos)]
            if key
        }
    )
    if not keys and isinstance(last_exit, dict):
        key = _contract_key(last_exit)
        if key:
            keys = [key]
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    return "multi:" + "|".join(keys)


def _exit_shadow_summary(
    state: dict[str, Any],
    soak_reset_at: str | None,
) -> dict[str, Any] | None:
    events = [
        event
        for event in (state.get("paper_shadow_events") or [])
        if isinstance(event, dict)
        and (
            not soak_reset_at
            or str(event.get("evaluated_at") or "") >= str(soak_reset_at)
        )
    ]
    if not events:
        return None
    brackets: dict[str, dict[str, Any]] = {}
    last_evaluated_at: str | None = None
    for event in events:
        evaluated_at = event.get("evaluated_at")
        if evaluated_at and (
            last_evaluated_at is None or str(evaluated_at) > last_evaluated_at
        ):
            last_evaluated_at = str(evaluated_at)
        for bracket in event.get("brackets") or []:
            if not isinstance(bracket, dict):
                continue
            bracket_id = bracket.get("bracket_id")
            if not bracket_id:
                continue
            summary = brackets.setdefault(
                str(bracket_id),
                {
                    "label": bracket.get("label"),
                    "would_exit": 0,
                    "would_hold": 0,
                    "would_hold_open": 0,
                    "would_hold_realized_pnl_usd": 0.0,
                    "last_exit_reason": None,
                },
            )
            if bracket.get("would_exit"):
                summary["would_exit"] += 1
            else:
                summary["would_hold"] += 1
            if bracket.get("exit_reason") is not None:
                summary["last_exit_reason"] = bracket.get("exit_reason")
        if event.get("event_type") == "virtual_hold_closed":
            bracket_id = event.get("bracket_id")
            if not bracket_id:
                continue
            summary = brackets.setdefault(
                str(bracket_id),
                {
                    "label": event.get("label"),
                    "would_exit": 0,
                    "would_hold": 0,
                    "would_hold_open": 0,
                    "would_hold_realized_pnl_usd": 0.0,
                    "last_exit_reason": None,
                },
            )
            summary["would_hold_realized_pnl_usd"] = round(
                float(summary["would_hold_realized_pnl_usd"])
                + float(event.get("paper_pnl_usd") or 0.0),
                2,
            )
            if event.get("exit_reason") is not None:
                summary["last_exit_reason"] = event.get("exit_reason")
    for hold in state.get("shadow_virtual_holds") or []:
        if not isinstance(hold, dict) or hold.get("status", "open") != "open":
            continue
        bracket_id = hold.get("bracket_id")
        if not bracket_id:
            continue
        summary = brackets.setdefault(
            str(bracket_id),
            {
                "label": hold.get("label"),
                "would_exit": 0,
                "would_hold": 0,
                "would_hold_open": 0,
                "would_hold_realized_pnl_usd": 0.0,
                "last_exit_reason": None,
            },
        )
        summary["would_hold_open"] += 1
    return {
        "events_evaluated": len(events),
        "last_evaluated_at": last_evaluated_at,
        "brackets": brackets,
    }


def _build_contract_clusters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        cluster_id = row.get("contract_cluster_id")
        if not cluster_id:
            continue
        cluster = clusters.setdefault(
            str(cluster_id),
            {
                "variant_ids": [],
                "variant_count": 0,
                "open_positions": 0,
                "trades_closed": 0,
                "realized_pnl_usd": 0.0,
            },
        )
        cluster["variant_ids"].append(row["variant_id"])
        cluster["variant_count"] = len(cluster["variant_ids"])
        cluster["open_positions"] += int(row.get("open_positions") or 0)
        cluster["trades_closed"] += int(row.get("trades_closed") or 0)
        cluster["realized_pnl_usd"] = round(
            float(cluster["realized_pnl_usd"])
            + float(row.get("realized_pnl_usd") or 0),
            2,
        )
    return clusters


def _build_regime_gate_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["variant_id"]: row for row in rows}
    comparison_rows: list[dict[str, Any]] = []
    for variant_id in REGIME_GATE_COMPARISON_IDS:
        row = by_id.get(variant_id)
        if row is None:
            continue
        comparison_rows.append(
            {
                "variant_id": variant_id,
                "description": row.get("description"),
                "logic_version": row.get("logic_version"),
                "regime_gate": row.get("regime_gate"),
                "regime_yellow_frac_min": row.get("regime_yellow_frac_min"),
                "track_family": row.get("track_family"),
                "sessions_evaluated": row.get("sessions_evaluated"),
                "entered_sessions": row.get("entered_sessions"),
                "trades_closed": row.get("trades_closed"),
                "realized_pnl_usd": row.get("realized_pnl_usd"),
                "avg_pnl_per_trade_usd": row.get("avg_pnl_per_trade_usd"),
                "bb_bounce_signal_sessions": row.get("bb_bounce_signal_sessions"),
                "bb_bounce_blocked_by_regime_sessions": row.get(
                    "bb_bounce_blocked_by_regime_sessions"
                ),
                "vol_shadow_would_block_sessions": row.get(
                    "vol_shadow_would_block_sessions"
                ),
                "vol_shadow_latest_spy_rv": row.get("vol_shadow_latest_spy_rv"),
                "vol_shadow_latest_would_block": row.get(
                    "vol_shadow_latest_would_block"
                ),
                "vol_shadow_avg_spy_rv": row.get("vol_shadow_avg_spy_rv"),
                "vs_baseline_avg_per_trade_usd": row.get(
                    "vs_baseline_avg_per_trade_usd"
                ),
            }
        )
    return {
        "description": (
            "Side-by-side GREEN baseline vs YELLOW bounce brackets (frac≥0.50 vs "
            "frac≥0.75). Independent shadow books — compare avg_pnl_per_trade_usd "
            "and how often each gate would have entered."
        ),
        "track_family": "yellow_bounce_frac_axis",
        "baseline_variant_id": "v2_baseline_prod",
        "variants": comparison_rows,
    }


def _promotion_meta(
    sessions_evaluated: int,
    trades_closed: int,
    entered_sessions: int,
) -> dict[str, Any]:
    remaining_sessions = max(0, PROMOTION_SESSIONS_GATE - sessions_evaluated)
    remaining_enters = max(0, PROMOTION_ENTERED_SESSIONS_GATE - entered_sessions)
    if sessions_evaluated < PROMOTION_SESSIONS_GATE:
        status = "collecting"
    elif entered_sessions < PROMOTION_ENTERED_SESSIONS_GATE:
        status = "insufficient_enters"
    elif trades_closed == 0:
        status = "sessions_met_no_trades"
    else:
        status = "eligible_review"
    return {
        "promotion_sessions_gate": PROMOTION_SESSIONS_GATE,
        "promotion_entered_sessions_gate": PROMOTION_ENTERED_SESSIONS_GATE,
        "sessions_to_promotion_gate": remaining_sessions,
        "entered_sessions_to_promotion_gate": remaining_enters,
        "promotion_status": status,
        "promotion_ready": status == "eligible_review",
    }


def _build_regime_skip_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-variant regime/skip distribution for cross-variant comparison (v4 GLM P2)."""
    variants: dict[str, dict[str, Any]] = {}
    for row in rows:
        variant_id = row.get("variant_id")
        if not variant_id:
            continue
        tel = row.get("entry_telemetry") or {}
        variants[str(variant_id)] = {
            "sessions_evaluated": row.get("sessions_evaluated"),
            "entered_sessions": row.get("entered_sessions"),
            "regime_gate_skip_sessions": row.get("regime_gate_skip_sessions"),
            "regime_counts": tel.get("regime_counts") or {},
            "skip_reason_counts": tel.get("skip_reason_counts") or {},
        }
    return {"variants": variants}


def _build_promotion_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        r["variant_id"]
        for r in rows
        if r.get("promotion_ready") and r.get("variant_id") != "v2_baseline_prod"
    ]
    collecting = sum(1 for r in rows if r.get("promotion_status") == "collecting")
    edge_confirmed = [
        r["variant_id"]
        for r in rows
        if r.get("edge_confirmed") and r.get("variant_id") != "v2_baseline_prod"
    ]
    return {
        "sessions_gate": PROMOTION_SESSIONS_GATE,
        "entered_sessions_gate": PROMOTION_ENTERED_SESSIONS_GATE,
        "variants_collecting": collecting,
        "variants_eligible_review": eligible,
        "variants_edge_confirmed": edge_confirmed,
        "baseline_promotion_ready": bool(
            next(
                (r for r in rows if r.get("variant_id") == "v2_baseline_prod"),
                {},
            ).get("promotion_ready")
        ),
    }


def wilson_lower_bound(wins: int, n: int, *, z: float = 1.96) -> float | None:
    """Wilson score-interval lower bound on the win rate (fraction 0-1).

    A small-n-honest floor on the true win rate: with few trades the bound sits
    well below the point estimate, so a lucky 4/5 run can't masquerade as edge.
    ``z=1.96`` ≈ 95% one-sided-ish confidence. Returns None when n<=0.
    """
    if n <= 0:
        return None
    phat = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _variant_breakeven_win_rate(rules_path: Path) -> float | None:
    """Breakeven win rate from the variant's TP/SL: SL / (TP + SL) (fraction).

    For +40% TP / -50% SL this is 0.50/0.90 ≈ 0.556 — the win rate a symmetric
    all-or-nothing bracket must beat to be +EV before costs.
    """
    try:
        data = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
        exit_cfg = data.get("exit") or {}
        tp = float(exit_cfg.get("take_profit_pct"))
        sl = float(exit_cfg.get("stop_loss_pct"))
    except Exception:
        return None
    if tp + sl <= 0:
        return None
    return sl / (tp + sl)


DIP_SWING_VARIANT_PREFIX = "v2_dip_swing"


def _dip_swing_exit_breakdown(row: dict[str, Any]) -> dict[str, Any] | None:
    """Compact per-variant exit-reason view so a cluster dominated by
    near-expiry time_stop exits is visible. Built additively from whatever
    exit-reason signal the scoreboard row already carries."""
    counts: dict[str, int] = {}
    last_exit = row.get("last_exit")
    if isinstance(last_exit, dict):
        reason = last_exit.get("exit_reason")
        if reason:
            counts[str(reason)] = counts.get(str(reason), 0) + 1
    exit_shadow = row.get("exit_shadow")
    if isinstance(exit_shadow, dict):
        for bracket in (exit_shadow.get("brackets") or {}).values():
            if not isinstance(bracket, dict):
                continue
            reason = bracket.get("last_exit_reason")
            if reason:
                counts[str(reason)] = counts.get(str(reason), 0) + 1
    if not counts:
        return None
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _build_dip_swing_cluster(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Isolate the dip-buy swing variants so the cluster can be watched as a
    group, separate from the legacy close-window variants. Ranked within the
    cluster by avg PnL per trade; a leader is only named once it clears the
    low-sample gate (>=20 sessions and >=20 trades)."""
    members = [
        r
        for r in rows
        if str(r.get("variant_id") or "").startswith(DIP_SWING_VARIANT_PREFIX)
    ]
    fields = (
        "variant_id",
        "description",
        "trades_closed",
        "wins",
        "losses",
        "win_rate_pct",
        "win_rate_wilson_lb_pct",
        "breakeven_win_rate_pct",
        "edge_confirmed",
        "realized_pnl_usd",
        "avg_pnl_per_trade_usd",
        "premium_scale",
        "realized_pnl_usd_1x_approx",
        "avg_pnl_per_trade_usd_1x_approx",
        "open_positions",
        "sessions_evaluated",
        "entered_sessions",
        "sessions_to_gate",
        "low_sample",
    )
    ranked = sorted(
        members,
        key=lambda r: (
            r.get("avg_pnl_per_trade_usd") is not None,
            r.get("avg_pnl_per_trade_usd") or -1e18,
        ),
        reverse=True,
    )
    trimmed = [{k: r.get(k) for k in fields} for r in ranked]
    for r, t in zip(ranked, trimmed):
        breakdown = _dip_swing_exit_breakdown(r)
        if breakdown is not None:
            t["exit_breakdown"] = breakdown
    total_trades = sum(int(r.get("trades_closed") or 0) for r in members)
    # A leader must clear statistical separation, not just the sample gate:
    # edge_confirmed = low_sample cleared AND avg_pnl>0 AND Wilson-LB win rate
    # above the variant's TP/SL breakeven.
    reliable = [r for r in members if r.get("edge_confirmed")]
    leader = None
    if reliable:
        leader = max(
            reliable,
            key=lambda r: r.get("avg_pnl_per_trade_usd") or -1e18,
        ).get("variant_id")
    return {
        "count": len(members),
        "total_trades_closed": total_trades,
        "ranked_by": "avg_pnl_per_trade_usd",
        "leader": leader,
        "leader_gate": (
            "edge_confirmed=true (>=20 sessions and >=20 trades, avg_pnl>0, "
            "Wilson-LB win rate > TP/SL breakeven)"
        ),
        "variants": trimmed,
        "note": (
            "Dip-buy swing cluster: buy a confirmed dip-bounce, hold for the "
            "recovery, sell into strength. Compare within this cluster; promote "
            "the leader to base once edge_confirmed. A leader must clear the "
            "sample gate AND show avg_pnl>0 AND a Wilson lower-bound win rate "
            "above its TP/SL breakeven (win_rate_wilson_lb_pct > "
            "breakeven_win_rate_pct) — small-n averages are noisy. "
            "*_1x_approx fields are the real-dollar (~$1k-account) equivalent, "
            "approx = paper_$ / premium_scale."
        ),
    }


def build_scoreboard(
    *,
    config_path: Path | None = None,
    state_path: Path | None = None,
    baseline_state_path: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    """Aggregate realized paper PnL per variant for comparison."""
    specs_list = load_variant_specs(config_path)
    specs = {s.variant_id: s for s in specs_list}
    root = load_variants_state(state_path)
    created = ensure_variant_slices(root, specs_list)
    if created:
        _write_variants_state(root, state_path)
    rows: list[dict[str, Any]] = []
    latest_entry_eval: datetime | None = None

    soak_reset_at = _soak_reset_at(root)

    def _summarize(
        variant_id: str,
        state: dict[str, Any],
        description: str,
        spec: VariantSpec | None = None,
    ) -> None:
        events = _events_in_soak_epoch(state, soak_reset_at)
        entry_logs = _entry_logs_in_soak_epoch(state, soak_reset_at)
        open_pos = [
            p
            for p in (state.get("paper_positions") or {}).values()
            if isinstance(p, dict) and p.get("status", "open") == "open"
        ]
        rules_path = merged_rules_path(spec) if spec is not None else DEFAULT_RULES
        nonlocal latest_entry_eval
        for row in entry_logs:
            evaluated_at = _parse_timestamp(row.get("evaluated_at"))
            if evaluated_at is None:
                continue
            if latest_entry_eval is None or evaluated_at > latest_entry_eval:
                latest_entry_eval = evaluated_at
        realized_pnls: list[float] = []
        trades_missing_pnl = 0
        for e in events:
            raw_pnl = e.get("paper_pnl_usd")
            if raw_pnl is None:
                trades_missing_pnl += 1
                continue
            try:
                realized_pnls.append(float(raw_pnl))
            except (TypeError, ValueError):
                trades_missing_pnl += 1
        realized = round(sum(realized_pnls), 2)
        wins = sum(1 for p in realized_pnls if p > 0)
        losses = sum(1 for p in realized_pnls if p < 0)
        trades = len(events)
        pnl_trades = len(realized_pnls)
        evals_total = len(entry_logs)
        weekend_evals_excluded = _weekend_eval_count(entry_logs)
        sessions_evaluated = len(unique_et_sessions(entry_logs))
        win_rate = round(wins / pnl_trades * 100.0, 1) if pnl_trades else None
        avg_pnl = round(realized / pnl_trades, 2) if pnl_trades else None
        # Dual-log the real-dollar (1x) equivalent so a $1k account can be judged
        # directly. Paper $ use the SPY->XSP premium scale (~10x); dividing by it
        # is a first-order approximation (fixed commission/slippage don't scale).
        try:
            scale = load_premium_scale(rules_path) or 1.0
        except Exception:
            scale = 1.0
        realized_1x = round(realized / scale, 2) if scale else realized
        avg_pnl_1x = (
            round(avg_pnl / scale, 2) if (avg_pnl is not None and scale) else avg_pnl
        )
        # Statistical separation: a leader must clear the sample gate AND show a
        # positive average AND a Wilson lower-bound win rate above its own
        # TP/SL breakeven — so small-n luck can't crown a noisy winner.
        low_sample_flag = (
            sessions_evaluated < PROMOTION_SESSIONS_GATE
            or trades < PROMOTION_TRADES_GATE
        )
        wilson_lb = wilson_lower_bound(wins, pnl_trades)
        breakeven = _variant_breakeven_win_rate(rules_path)
        edge_confirmed = bool(
            not low_sample_flag
            and avg_pnl is not None
            and avg_pnl > 0
            and wilson_lb is not None
            and breakeven is not None
            and wilson_lb > breakeven
        )
        last_exit = _last_exit_with_contract_meta(state, events)
        contract_cluster_id = _contract_cluster_id(
            open_positions=open_pos,
            last_exit=last_exit,
        )
        row: dict[str, Any] = {
            "variant_id": variant_id,
            "description": description,
            "trades_closed": trades,
            "trades_missing_pnl": trades_missing_pnl,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate,
            "realized_pnl_usd": realized,
            "avg_pnl_per_trade_usd": avg_pnl,
            "premium_scale": round(scale, 4),
            "realized_pnl_usd_1x_approx": realized_1x,
            "avg_pnl_per_trade_usd_1x_approx": avg_pnl_1x,
            "win_rate_wilson_lb_pct": (
                round(wilson_lb * 100.0, 1) if wilson_lb is not None else None
            ),
            "breakeven_win_rate_pct": (
                round(breakeven * 100.0, 1) if breakeven is not None else None
            ),
            "edge_confirmed": edge_confirmed,
            "sessions_evaluated": sessions_evaluated,
            "entry_evals_total": evals_total,
            "weekend_evals_excluded": weekend_evals_excluded,
            "sessions_to_gate": max(0, 20 - sessions_evaluated),
            "open_positions": len(open_pos),
            "last_exit": last_exit,
            "contract_cluster_id": contract_cluster_id,
            "low_sample": low_sample_flag,
        }
        row.update(_variant_track_meta(variant_id, spec))
        entry_stats = _entry_session_stats(entry_logs)
        row.update(entry_stats)
        row.update(_vol_shadow_session_stats(entry_logs))
        row.update(_open_positions_metrics(state, rules_path=rules_path))
        row.update(
            _promotion_meta(
                sessions_evaluated,
                trades,
                int(entry_stats.get("entered_sessions") or 0),
            )
        )
        tel = summarize_entry_telemetry_from_logs(entry_logs)
        if tel.get("evals_total", 0) > 0:
            row["entry_telemetry"] = {
                "skip_reason_counts": tel.get("skip_reason_counts") or {},
                "regime_counts": tel.get("regime_counts") or {},
                "evals_total": tel.get("evals_total", 0),
                "entered_sessions": tel.get("entered_sessions", 0),
            }
        exit_shadow = _exit_shadow_summary(state, soak_reset_at)
        if exit_shadow is not None:
            row["exit_shadow"] = exit_shadow
        rows.append(row)

    # Shadow variants
    state_variants = root.get("variants") or {}
    active_specs = [spec for spec in specs.values() if spec.active]
    variant_ids = list(
        dict.fromkeys(
            [spec.variant_id for spec in active_specs] + list(state_variants.keys())
        )
    )
    for variant_id in variant_ids:
        spec = specs.get(variant_id)
        if spec is not None and not spec.active:
            continue
        raw_slice_state = state_variants.get(variant_id)
        slice_state = raw_slice_state if isinstance(raw_slice_state, dict) else {}
        desc = spec.description if spec else ""
        _summarize(variant_id, slice_state, desc, spec=spec)

    # Production baseline from main state
    baseline_path = baseline_state_path or (ROOT / "briefs" / "xsp-lane-a-state.json")
    if baseline_path.is_file():
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            _summarize(
                "v2_baseline_prod",
                baseline,
                "Production lane_a_rules.yaml (systemd cron)",
                spec=None,
            )
        except (json.JSONDecodeError, OSError):
            pass

    baseline_row = next(
        (r for r in rows if r["variant_id"] == "v2_baseline_prod"), None
    )
    shadow_rows = [r for r in rows if r["variant_id"] != "v2_baseline_prod"]
    baseline_avg = (baseline_row or {}).get("avg_pnl_per_trade_usd")
    for row in shadow_rows:
        avg = row.get("avg_pnl_per_trade_usd")
        if baseline_avg is not None and avg is not None:
            row["vs_baseline_avg_per_trade_usd"] = round(avg - baseline_avg, 2)
        else:
            row["vs_baseline_avg_per_trade_usd"] = None

    ranking_reliable = sum(1 for row in shadow_rows if not row.get("low_sample")) >= 2
    if ranking_reliable:
        shadow_rows.sort(
            key=lambda r: (
                r.get("avg_pnl_per_trade_usd") is not None,
                r.get("avg_pnl_per_trade_usd") or -1e18,
            ),
            reverse=True,
        )
    else:
        shadow_rows.sort(key=lambda r: str(r.get("variant_id") or ""))
    ordered = shadow_rows + ([baseline_row] if baseline_row else [])
    contract_clusters = _build_contract_clusters(ordered)
    updated_at_dt = datetime.now(timezone.utc)
    updated_at = updated_at_dt.isoformat()
    last_entry_eval_at = latest_entry_eval.isoformat() if latest_entry_eval else None
    stale = scoreboard_entry_stale(latest_entry_eval, now=updated_at_dt)
    payload = {
        "updated_at": updated_at,
        "soak_reset_at": soak_reset_at,
        "pnl_epoch_at": root.get("pnl_epoch_at") or soak_reset_at,
        "soak_reset_commit": root.get("soak_reset_commit"),
        "pnl_epoch_commit": root.get("pnl_epoch_commit"),
        "active_variant_ids": [spec.variant_id for spec in active_specs],
        "state_variant_ids": sorted(
            variant_id
            for variant_id, raw in state_variants.items()
            if isinstance(raw, dict)
        ),
        "last_entry_eval_at": last_entry_eval_at,
        "stale": stale,
        "comparison_guidance": (
            "Rank shadow variants by avg_pnl_per_trade_usd vs v2_baseline_prod. "
            "Do NOT sum PnL across variants — configs are independent experiments."
        ),
        "ranked_by": "avg_pnl_per_trade_usd",
        "ranking_reliable": ranking_reliable,
        "baseline_prod": baseline_row,
        "shadow_variants": shadow_rows,
        "variants": ordered,
        "contract_clusters": contract_clusters,
        "regime_gate_comparison": _build_regime_gate_comparison(rows),
        "regime_skip_breakdown": _build_regime_skip_breakdown(rows),
        "dip_swing_cluster": _build_dip_swing_cluster(shadow_rows),
        "promotion_summary": _build_promotion_summary(rows),
        "note": (
            "Per-variant comparison only. Need ≥20 post-epoch sessions per variant before promotion."
        ),
    }
    out = out_path or DEFAULT_SCOREBOARD
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if baseline_path.is_file():
        try:
            baseline_state = json.loads(baseline_path.read_text(encoding="utf-8"))
            write_paper_pnl_brief(
                baseline_state,
                out_path=_baseline_brief_path(baseline_path, DEFAULT_PAPER_BRIEF),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("paper brief regen after scoreboard failed: %s", exc)

    return out
