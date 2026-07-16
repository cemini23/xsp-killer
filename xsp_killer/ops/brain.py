"""Brain JSON: pull audit, bt_* additive keys for the backtest sensor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xsp_killer.ops.paths import brain_path, ensure_layout
from xsp_killer.ops.state import read_json, write_json

PULL_LOG_MAX = 20

# Additive vs OSINT DEFAULT_BRAIN so a shared root stays compatible.
DEFAULT_BRAIN: dict[str, Any] = {
    "last_pull_at": None,
    "items_seen": 0,
    "pull_log": [],
    "bt_post_ids": [],
    "bt_known_reports": [],
}


def empty_brain() -> dict[str, Any]:
    return dict(DEFAULT_BRAIN)


def load_brain(root: Path | None = None) -> dict[str, Any]:
    ensure_layout(root)
    path = brain_path(root)
    data = read_json(path, empty_brain())
    if not isinstance(data, dict):
        return empty_brain()
    out = empty_brain()
    out.update(data)
    for key in ("pull_log", "bt_post_ids", "bt_known_reports"):
        if not isinstance(out.get(key), list):
            out[key] = []
    return out


def save_brain(brain: dict[str, Any], root: Path | None = None) -> Path:
    ensure_layout(root)
    path = brain_path(root)
    log = list(brain.get("pull_log") or [])
    if len(log) > PULL_LOG_MAX:
        brain = dict(brain)
        brain["pull_log"] = log[-PULL_LOG_MAX:]
    write_json(path, brain)
    return path


def append_pull_log(brain: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Append one pull audit row; keep last PULL_LOG_MAX."""
    log = list(brain.get("pull_log") or [])
    log.append(entry)
    brain["pull_log"] = log[-PULL_LOG_MAX:]
    return brain


def mark_bt_landed(
    brain: dict[str, Any],
    slug: str,
    report_json: str,
) -> dict[str, Any]:
    """Record a backtest post id + report path (additive bt_* keys)."""
    ids = list(brain.get("bt_post_ids") or [])
    paths = list(brain.get("bt_known_reports") or [])
    if slug not in ids:
        ids.append(slug)
    if report_json and report_json not in paths:
        paths.append(report_json)
    brain["bt_post_ids"] = ids
    brain["bt_known_reports"] = paths
    return brain
