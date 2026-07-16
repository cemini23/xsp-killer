"""Emit Nagus ops state from a Lane A backtest report payload.

Fail-open at the CLI boundary; this module raises only on hard misuse.
Never writes under briefs/ or wiki/. Never flips LIVE_* flags.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from xsp_killer.ops.brain import (
    append_pull_log,
    load_brain,
    mark_bt_landed,
    save_brain,
)
from xsp_killer.ops.packet_render import (
    existing_packet_for_slug,
    write_packet,
)
from xsp_killer.ops.paths import (
    ensure_layout,
    events_dir,
    packets_dir,
    posts_path,
    resolve_ops_root,
)
from xsp_killer.ops.queue import count_jobs, find_job, write_pending
from xsp_killer.ops.rules import classify_variant
from xsp_killer.ops.state import utc_now_iso, write_json

logger = logging.getLogger("xsp_killer.ops.emit")

SENSOR = "backtest_lane_a"
DEFAULT_SCALE_PENDING = 5


def _scale_pending_threshold() -> int:
    raw = os.environ.get("XSP_OPS_SCALE_PENDING", str(DEFAULT_SCALE_PENDING))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_SCALE_PENDING


def sanitize_slug_part(text: str) -> str:
    """Filesystem-safe token: [\\w\\-] only."""
    s = re.sub(r"[^\w\-]+", "-", str(text)).strip("-")
    return s or "x"


def report_stem_from_path(report_json: Path | str | None) -> str:
    if report_json is None:
        return "unknown"
    stem = Path(report_json).stem
    # lane_a_bt_20260716T120000Z → 20260716T120000Z
    if stem.startswith("lane_a_bt_"):
        return stem[len("lane_a_bt_") :]
    return stem or "unknown"


def make_slug(report_stem: str, variant_id: str) -> str:
    return f"bt_{sanitize_slug_part(report_stem)}_{sanitize_slug_part(variant_id)}"


def _rel_or_str(path: Path | str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    try:
        # Prefer repo-relative when under cwd / known trees
        return str(p.as_posix())
    except Exception:
        return str(path)


def emit_from_report(
    payload: dict[str, Any],
    *,
    report_json: Path | str | None = None,
    report_md: Path | str | None = None,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Land brain/posts/queue/packets from a backtest report payload.

    Returns a summary dict. Does not write under briefs/ or wiki/.
    """
    ops_root = resolve_ops_root(root)
    ranking = list(payload.get("ranking") or [])
    report_stem = report_stem_from_path(report_json)
    report_json_s = _rel_or_str(report_json)
    report_md_s = _rel_or_str(report_md)
    mode = str(payload.get("mode") or "")
    source = str(payload.get("source") or "")
    generated_at = str(payload.get("generated_at") or utc_now_iso())

    classifications: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    n_mcpt_pass = 0

    for i, row in enumerate(ranking, start=1):
        clf = classify_variant(row, rank=i)
        entry = {"rank": i, "row": row, "clf": clf}
        classifications.append(entry)
        if row.get("mcpt_pass_5pct") is True:
            n_mcpt_pass += 1
        if clf.get("action") in ("packet", "watch"):
            candidates.append(entry)

    top_variant = None
    top_mean = None
    if ranking:
        top_variant = ranking[0].get("variant_id")
        top_mean = ranking[0].get("mean_net_pnl_pct")

    pull_entry: dict[str, Any] = {
        "at": utc_now_iso(),
        "sensor": SENSOR,
        "mode": mode,
        "source": source,
        "report_json": report_json_s,
        "report_md": report_md_s,
        "n_variants": len(ranking),
        "n_candidates": len(candidates),
        "n_mcpt_pass": n_mcpt_pass,
        "top_variant": top_variant,
        "top_mean_net_pct": top_mean,
        "dry_run": bool(dry_run),
    }

    summary: dict[str, Any] = {
        "ops_root": str(ops_root),
        "dry_run": bool(dry_run),
        "n_variants": len(ranking),
        "n_candidates": len(candidates),
        "n_mcpt_pass": n_mcpt_pass,
        "top_variant": top_variant,
        "posts_written": [],
        "jobs_enqueued": [],
        "packets_written": [],
        "jobs_skipped_existing": [],
        "packets_skipped_existing": [],
        "pull_log_entry": pull_entry,
        "scale_event": None,
        "candidates": [
            {
                "variant_id": c["row"].get("variant_id"),
                "slug": make_slug(report_stem, str(c["row"].get("variant_id") or "")),
                **c["clf"],
            }
            for c in candidates
        ],
    }

    if dry_run:
        logger.info(
            "nagus dry-run: n_variants=%s n_candidates=%s n_mcpt_pass=%s root=%s",
            len(ranking),
            len(candidates),
            n_mcpt_pass,
            ops_root,
        )
        return summary

    ensure_layout(ops_root)
    now = utc_now_iso()
    brain = load_brain(ops_root)
    append_pull_log(brain, pull_entry)
    brain["last_pull_at"] = now
    brain["items_seen"] = int(brain.get("items_seen") or 0) + len(ranking)

    for c in candidates:
        row = c["row"]
        clf = c["clf"]
        variant_id = str(row.get("variant_id") or "unknown")
        slug = make_slug(report_stem, variant_id)

        post: dict[str, Any] = {
            "slug": slug,
            "kind": "backtest_variant",
            "sensor": SENSOR,
            "variant_id": variant_id,
            "report_json": report_json_s,
            "report_md": report_md_s,
            "generated_at": generated_at,
            "mode": mode,
            "source": source,
            "n_trades": row.get("n_trades"),
            "win_pct": row.get("win_pct"),
            "mean_net_pnl_pct": row.get("mean_net_pnl_pct"),
            "median_net_pnl_pct": row.get("median_net_pnl_pct"),
            "total_pnl_usd": row.get("total_pnl_usd"),
            "mcpt_p": row.get("mcpt_p"),
            "mcpt_pass_5pct": row.get("mcpt_pass_5pct"),
            "status": clf["status"],
            "priority": clf["priority"],
            "action": clf["action"],
            "reason": clf["reason"],
            "landed_at": now,
            "packet_path": None,
        }

        # Packet only for action=packet
        if clf["action"] == "packet":
            pdir = packets_dir(ops_root)
            existing = existing_packet_for_slug(pdir, slug)
            if existing is not None:
                post["packet_path"] = str(existing)
                summary["packets_skipped_existing"].append(str(existing))
            else:
                pkt = write_packet(post, pdir)
                post["packet_path"] = str(pkt)
                summary["packets_written"].append(str(pkt))

        post_path = posts_path(slug, ops_root)
        write_json(post_path, post)
        summary["posts_written"].append(str(post_path))
        mark_bt_landed(brain, slug, report_json_s or "")

        # Enqueue for packet and watch
        if find_job(slug, ops_root) is not None:
            summary["jobs_skipped_existing"].append(slug)
        else:
            job_path = write_pending(
                slug,
                root=ops_root,
                extra={
                    "kind": "backtest_variant",
                    "sensor": SENSOR,
                    "variant_id": variant_id,
                    "priority": clf["priority"],
                    "action": clf["action"],
                    "report_json": report_json_s,
                },
            )
            summary["jobs_enqueued"].append(str(job_path))

    # Ensure report path is recorded even when no candidates landed
    if report_json_s:
        known = list(brain.get("bt_known_reports") or [])
        if report_json_s not in known:
            known.append(report_json_s)
            brain["bt_known_reports"] = known

    save_brain(brain, ops_root)

    # Optional scale event (event JSON only — no osascript/Discord on Linux)
    pending_n = count_jobs("pending", ops_root)
    thr = _scale_pending_threshold()
    if pending_n >= thr:
        event = {
            "type": "escalate",
            "at": utc_now_iso(),
            "sensor": SENSOR,
            "pending": pending_n,
            "threshold": thr,
            "reasons": ["pending_ge_threshold"],
            "message": (
                f"XSP backtest ops escalate: pending={pending_n} "
                f"candidates awaiting review"
            ),
        }
        ts = event["at"].replace(":", "").replace("+", "Z")
        event_path = events_dir(ops_root) / f"escalate_{ts}.json"
        write_json(event_path, event)
        summary["scale_event"] = str(event_path)
        logger.info("nagus scale event: %s", event_path)

    logger.info(
        "nagus emit: posts=%s jobs=%s packets=%s candidates=%s root=%s",
        len(summary["posts_written"]),
        len(summary["jobs_enqueued"]),
        len(summary["packets_written"]),
        len(candidates),
        ops_root,
    )
    return summary
