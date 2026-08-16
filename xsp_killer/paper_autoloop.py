"""Unattended paper tick — Lane A + Lane PC sleeves.

Forces LIVE_* false for this process. Never places multi-leg.
"""

from __future__ import annotations

import json
import math
import os
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from xsp_killer.put_credit import (
    build_put_credit,
    put_credit_value,
    select_long_put_strike,
)
from xsp_killer.tipseeker_shadow import load_latest_tipseeker
from xsp_killer.uw_put_marks import PutCreditMarks, fetch_live_put_credit_marks
from xsp_killer.put_credit_paper import (
    DEFAULT_LOG,
    DEFAULT_RULES,
    DEFAULT_SCOREBOARD,
    DEFAULT_STATE,
    ET,
    PcRules,
    _atm,
    _bs_put,
    _spread_mark,
    append_log,
    evaluate_pc_exits,
    evaluate_pc_gates,
    load_state,
    save_state,
    write_scoreboard,
)

ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT = ROOT / "briefs" / "paper-autoloop-latest.json"
TICK_LOG = ROOT / "logs" / "paper_tick.jsonl"
STRIKE_STEP = 5.0


@dataclass
class SpySnapshot:
    close: float
    ma20: float
    rv20: float
    asof: str
    mark_value: float | None = None


def load_paper_overlays() -> dict[str, Any]:
    """TipSeeker DB + UW IV/tide. Log-only. Never vetoes. Fail-open."""
    out: dict[str, Any] = {
        "shadow_only": True,
        "veto": False,
        "tipseeker": None,
        "iv_rank": None,
        "market_tide": None,
    }
    try:
        out["tipseeker"] = load_latest_tipseeker()
    except Exception:
        out["tipseeker"] = None
    try:
        from xsp_killer.uw_shadow import (
            _get_provider,
            build_iv_rank_summary,
            fetch_market_tide_summary,
        )

        provider = _get_provider()
        if provider is not None:
            out["iv_rank"] = build_iv_rank_summary(provider, ticker="SPY")
            out["market_tide"] = fetch_market_tide_summary(provider)
    except Exception:
        pass
    return out


def force_paper_only_env() -> None:
    os.environ["XSP_LANE_A_LIVE_ENTRIES"] = "false"
    os.environ["XSP_LANE_A_LIVE_EXITS"] = "false"
    os.environ["XSP_LANE_A_PAPER_ENTRY"] = "true"


def fetch_spy_snapshot(ma_period: int = 20) -> SpySnapshot:
    import pandas as pd
    import yfinance as yf

    hist = yf.Ticker("SPY").history(period="3mo", interval="1d", timeout=15)
    if hist is None or hist.empty or len(hist) < ma_period:
        raise RuntimeError("spy_history_unavailable")
    close = float(hist["Close"].iloc[-1])
    ma20 = float(hist["Close"].tail(ma_period).mean())
    rets = hist["Close"].pct_change()
    rv = float(rets.tail(20).std(ddof=1) * math.sqrt(252))
    if not math.isfinite(rv) or rv <= 0:
        rv = 0.16
    asof = hist.index[-1]
    asof_s = asof.date().isoformat() if hasattr(asof, "date") else str(asof)[:10]
    return SpySnapshot(close=close, ma20=ma20, rv20=min(max(rv, 0.08), 0.80), asof=asof_s)


def _today(now_et: datetime) -> date:
    now = now_et.astimezone(ET) if now_et.tzinfo else now_et.replace(tzinfo=ET)
    return now.date()


def _bump_sessions(pos: dict[str, Any], today: date) -> int:
    last = pos.get("last_monitor_date")
    held = int(pos.get("sessions_held") or 0)
    if last != today.isoformat():
        if last:
            held += 1
        pos["sessions_held"] = held
        pos["last_monitor_date"] = today.isoformat()
    return held


def _open_pc_position(
    *,
    rules: PcRules,
    snapshot: SpySnapshot,
    now_et: datetime,
    live_marks: bool = False,
    mark_fn: Callable[..., PutCreditMarks | None] | None = None,
) -> dict[str, Any]:
    width = float(rules.width_strikes) * STRIKE_STEP
    iv = min(max(float(snapshot.rv20), 0.08), 0.80)
    short_k = _atm(snapshot.close)
    long_k = select_long_put_strike(short_k, width_strikes=rules.width_strikes)
    fidelity = "modeled_bs_rv20"
    short_p = _bs_put(snapshot.close, short_k, rules.dte, iv)
    long_p = _bs_put(snapshot.close, long_k, rules.dte, iv)
    if live_marks:
        fn = mark_fn or fetch_live_put_credit_marks
        try:
            marks = fn(
                short_k=short_k,
                long_k=long_k,
                dte=rules.dte,
                today=_today(now_et),
            )
        except Exception:
            marks = None
        if marks is not None and marks.net_credit > 0:
            short_p = marks.short_mid
            long_p = marks.long_mid
            fidelity = marks.source
    built = build_put_credit(
        short_strike=short_k,
        short_premium=short_p,
        long_strike=long_k,
        long_premium=long_p,
        premium_scale=1.0,
    )
    if built is None:
        raise RuntimeError("pc_credit_unbuildable")
    day = _today(now_et).isoformat()
    return {
        "position_id": f"pc-{day}-{int(short_k)}",
        "entry_date": day,
        "entry_credit": built.net_credit,
        "width_points": width,
        "short_strike": short_k,
        "long_strike": long_k,
        "iv": iv,
        "mark_value": built.net_credit,
        "above_ma20": snapshot.close > snapshot.ma20,
        "sessions_held": 0,
        "last_monitor_date": day,
        "dte": rules.dte,
        "pricing_fidelity": fidelity,
        "live_untouched": True,
    }


def run_pc_cycle(
    *,
    rules: PcRules,
    state: dict[str, Any],
    snapshot: SpySnapshot,
    now_et: datetime,
    log_path: Path | None = None,
    live_marks: bool = False,
    mark_fn: Callable[..., PutCreditMarks | None] | None = None,
    overlays: dict[str, Any] | None = None,
) -> dict[str, Any]:
    log = log_path or DEFAULT_LOG
    open_pos = state.setdefault("paper_positions", {})
    closed = state.setdefault("closed", [])
    today = _today(now_et)

    still: dict[str, Any] = {}
    exited: dict[str, Any] | None = None
    for pid, pos in list(open_pos.items()):
        pos = dict(pos)
        held = _bump_sessions(pos, today)
        pos["above_ma20"] = snapshot.close > snapshot.ma20
        if snapshot.mark_value is not None:
            pos["mark_value"] = float(snapshot.mark_value)
        else:
            width = float(pos.get("width_points") or rules.width_strikes * STRIKE_STEP)
            dte_left = max(0, int(pos.get("dte") or rules.dte) - held)
            used_live = False
            if live_marks:
                fn = mark_fn or fetch_live_put_credit_marks
                try:
                    marks = fn(
                        short_k=float(pos["short_strike"]),
                        long_k=float(pos["long_strike"]),
                        dte=dte_left,
                        today=today,
                    )
                except Exception:
                    marks = None
                if marks is not None:
                    pos["mark_value"] = put_credit_value(
                        short_mark=marks.short_mid,
                        long_mark=marks.long_mid,
                        width=width,
                    )
                    pos["pricing_fidelity"] = marks.source
                    used_live = True
            if not used_live:
                pos["mark_value"] = _spread_mark(
                    snapshot.close,
                    float(pos["short_strike"]),
                    float(pos["long_strike"]),
                    dte_left,
                    float(pos.get("iv") or snapshot.rv20),
                    width,
                )
        reason = evaluate_pc_exits(pos, now_et=now_et, sessions_held=held, rules=rules)
        if reason:
            pos["status"] = "closed"
            pos["exit_reason"] = reason
            pos["exit_ts"] = datetime.now(timezone.utc).isoformat()
            closed.append(pos)
            exited = {
                "event": "pc_exit",
                "reason": reason,
                "position": pos,
                "overlays_veto": False,
            }
            append_log(exited, log)
        else:
            still[pid] = pos
    state["paper_positions"] = still
    if exited:
        return exited

    if still:
        row = {
            "event": "pc_hold",
            "open": len(still),
            "allowed": False,
            "reason": "already_open",
            "overlays_veto": False,
        }
        append_log(row, log)
        return row

    gate = evaluate_pc_gates(
        now_et=now_et, close=snapshot.close, ma20=snapshot.ma20, rules=rules
    )
    if not gate.allowed:
        row = {
            "event": "pc_entry_skip",
            "allowed": False,
            "reason": gate.reason,
            "close": snapshot.close,
            "ma20": snapshot.ma20,
            "overlays_veto": False,
        }
        append_log(row, log)
        return row

    pos = _open_pc_position(
        rules=rules,
        snapshot=snapshot,
        now_et=now_et,
        live_marks=live_marks,
        mark_fn=mark_fn,
    )
    state["paper_positions"][pos["position_id"]] = pos
    row = {
        "event": "pc_entry",
        "allowed": True,
        "reason": None,
        "position": pos,
        "close": snapshot.close,
        "ma20": snapshot.ma20,
        "live_untouched": True,
        "overlays_veto": False,
        "overlays": overlays,
    }
    append_log(row, log)
    return row


def _pc_paths_from_yaml(rules_path: Path) -> tuple[Path, Path, Path]:
    import yaml

    data = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    logging_cfg = data.get("logging") or {}
    log = ROOT / logging_cfg.get("log_path", "logs/lane_pc_paper.jsonl")
    state = ROOT / logging_cfg.get("state_path", "briefs/lane-pc-state.json")
    score = ROOT / logging_cfg.get("scoreboard_path", "briefs/lane-pc-scoreboard.json")
    return log, state, score


def run_pc_sleeve(
    *,
    rules_path: Path,
    snapshot: SpySnapshot,
    now_et: datetime,
    overlays: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = PcRules.from_yaml(rules_path)
    log, state_path, score_path = _pc_paths_from_yaml(rules_path)
    state = load_state(state_path)
    out = run_pc_cycle(
        rules=rules,
        state=state,
        snapshot=snapshot,
        now_et=now_et,
        log_path=log,
        live_marks=True,
        overlays=overlays,
    )
    save_state(state, state_path)
    closed = state.get("closed") or []
    if closed:
        wins = sum(1 for t in closed if (t.get("pnl_usd") or 0) > 0)
        n = len(closed)
        write_scoreboard(
            {
                "n_entries": n,
                "win_pct": round(100.0 * wins / n, 2) if n else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "live_untouched": True,
                "last_event": out.get("event"),
            },
            score_path,
        )
    return out


def _run_lane_a_paper(*, now_et: datetime) -> dict[str, Any]:
    from xsp_killer.lane_a_entry import run_paper_entry
    from xsp_killer.lane_a_intraday import run_intraday_cycle
    from xsp_killer.lane_a_monitor import run_monitor
    from xsp_killer.lane_a_variants import (
        run_all_variant_entries,
        run_all_variant_monitors,
    )

    entry = run_paper_entry(now_et=now_et, force=False, publish_intel=False)
    monitor = run_monitor(now_et=now_et)
    intra = run_intraday_cycle(now_et=now_et, publish_intel=False)
    variants_entry = run_all_variant_entries(now_et=now_et, force=False)
    variants_mon = run_all_variant_monitors(now_et=now_et)
    return {
        "ok": True,
        "lane_a_entered": bool(getattr(entry, "entered", False)),
        "lane_a_skip": getattr(entry, "skip_reason", None),
        "monitor": "ok" if monitor is not None else None,
        "intraday": "ok" if intra is not None else None,
        "variants_entry": "ok" if variants_entry is not None else None,
        "variants_monitor": "ok" if variants_mon is not None else None,
    }


def run_paper_tick(
    *,
    now_et: datetime | None = None,
    snapshot: SpySnapshot | None = None,
    run_lane_a: bool = True,
    pc_sleeves: list[Path] | None = None,
    heartbeat_path: Path | None = None,
    log_path: Path | None = None,
    fetch: Callable[[], SpySnapshot] = fetch_spy_snapshot,
) -> dict[str, Any]:
    force_paper_only_env()
    now = now_et or datetime.now(ET)
    snap = snapshot or fetch()
    try:
        overlays = load_paper_overlays()
    except Exception:
        overlays = {"shadow_only": True, "veto": False}
    sleeves: dict[str, Any] = {}

    if run_lane_a:
        try:
            sleeves["lane_a"] = _run_lane_a_paper(now_et=now)
        except Exception as exc:
            sleeves["lane_a"] = {"ok": False, "error": str(exc), "trace": traceback.format_exc()}

    paths = pc_sleeves if pc_sleeves is not None else [
        ROOT / "config" / "lane_pc_rules.yaml",
        ROOT / "config" / "lane_pc_7dte_rules.yaml",
    ]
    for path in paths:
        name = path.stem
        try:
            sleeves[name] = {
                "ok": True,
                **run_pc_sleeve(
                    rules_path=path, snapshot=snap, now_et=now, overlays=overlays
                ),
            }
        except Exception as exc:
            sleeves[name] = {"ok": False, "error": str(exc)}

    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "asof": snap.asof,
        "close": snap.close,
        "ma20": snap.ma20,
        "sleeves": sleeves,
        "overlays": overlays,
        "live_untouched": True,
        "live_entries": os.environ.get("XSP_LANE_A_LIVE_ENTRIES"),
        "live_exits": os.environ.get("XSP_LANE_A_LIVE_EXITS"),
    }
    hb = heartbeat_path or HEARTBEAT
    hb.parent.mkdir(parents=True, exist_ok=True)
    hb.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    append_log(result, log_path or TICK_LOG)
    return result
