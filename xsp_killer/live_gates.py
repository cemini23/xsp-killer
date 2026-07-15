"""Hard human gates for any live Robinhood placement.

Paper / shadow soak may run all active variants. Live writes require an
explicit two-key human promotion of a single ``variant_id``:

1. ``XSP_LANE_A_LIVE_VARIANT_ID`` — exact promoted logic_version / variant id
2. ``XSP_LANE_A_LIVE_HUMAN_ACK`` — must equal the same id (typed twice on purpose)
3. Optional ack file (default ``.local/LIVE_HUMAN_REVIEW.json``) with matching
   ``variant_id`` and the literal statement
   ``I reviewed the scoreboard and promote this variant to live``

Any of the three missing or mismatched → live places are blocked (fail-closed).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("xsp_killer.live_gates")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACK_PATH = ROOT / ".local" / "LIVE_HUMAN_REVIEW.json"
REQUIRED_STATEMENT = (
    "I reviewed the scoreboard and promote this variant to live"
)


def _ack_path() -> Path:
    raw = os.getenv("XSP_LANE_A_LIVE_HUMAN_ACK_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_ACK_PATH


def live_variant_id() -> str:
    return (os.getenv("XSP_LANE_A_LIVE_VARIANT_ID") or "").strip()


def live_human_ack_env() -> str:
    return (os.getenv("XSP_LANE_A_LIVE_HUMAN_ACK") or "").strip()


def load_human_review_file(path: Path | None = None) -> dict[str, Any] | None:
    p = path or _ack_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("live human review file unreadable at %s: %s", p, exc)
        return None
    return data if isinstance(data, dict) else None


def human_variant_review_allows(current_variant: str) -> tuple[bool, str]:
    """Fail-closed gate for live place (entry or exit).

    Returns ``(ok, reason)``. ``ok`` is True only when env dual-ack and the
    review file all name the same non-empty variant that equals ``current_variant``.
    """
    current = (current_variant or "").strip()
    allowed = live_variant_id()
    ack_env = live_human_ack_env()
    if not current:
        return False, "live human review blocked — empty current variant"
    if not allowed:
        return False, "live human review blocked — XSP_LANE_A_LIVE_VARIANT_ID unset"
    if current != allowed:
        return False, (
            f"live human review blocked — variant {current!r} != "
            f"LIVE_VARIANT_ID {allowed!r}"
        )
    if not ack_env:
        return False, "live human review blocked — XSP_LANE_A_LIVE_HUMAN_ACK unset"
    if ack_env != allowed:
        return False, (
            "live human review blocked — XSP_LANE_A_LIVE_HUMAN_ACK must exactly "
            f"equal LIVE_VARIANT_ID ({allowed!r})"
        )
    review = load_human_review_file()
    if review is None:
        return False, (
            f"live human review blocked — missing ack file {_ack_path()} "
            f'(needs variant_id + statement "{REQUIRED_STATEMENT}")'
        )
    file_vid = str(review.get("variant_id") or "").strip()
    statement = str(review.get("statement") or "").strip()
    if file_vid != allowed:
        return False, (
            f"live human review blocked — ack file variant_id {file_vid!r} "
            f"!= LIVE_VARIANT_ID {allowed!r}"
        )
    if statement != REQUIRED_STATEMENT:
        return False, (
            "live human review blocked — ack file statement must be exactly "
            f"{REQUIRED_STATEMENT!r}"
        )
    return True, "human variant review ok"


def require_human_variant_review(current_variant: str) -> None:
    """Raise ``RuntimeError`` if the hard human review gate fails."""
    ok, reason = human_variant_review_allows(current_variant)
    if not ok:
        raise RuntimeError(reason)
