"""Render backtest staging packet markdown (never under briefs/)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def packet_filename(slug: str, day: date | None = None) -> str:
    d = day or datetime.now(timezone.utc).date()
    safe = re.sub(r"[^\w\-]+", "-", slug).strip("-") or "variant"
    return f"{d.isoformat()}_{safe}.md"


def render_packet_markdown(post: dict[str, Any]) -> str:
    variant_id = post.get("variant_id") or post.get("slug") or "unknown"
    status = post.get("status") or "—"
    priority = post.get("priority") or "—"
    mode = post.get("mode") or "—"
    source = post.get("source") or "—"
    n_trades = post.get("n_trades", "—")
    win_pct = post.get("win_pct")
    mean_p = post.get("mean_net_pnl_pct")
    med_p = post.get("median_net_pnl_pct")
    total_usd = post.get("total_pnl_usd")
    mcpt_p = post.get("mcpt_p")
    mcpt_pass = post.get("mcpt_pass_5pct")
    report_json = post.get("report_json") or "—"
    reason = post.get("reason") or "—"

    win_s = f"{win_pct:.2f}" if isinstance(win_pct, (int, float)) else str(win_pct)
    mean_s = (
        f"{100 * mean_p:.2f}"
        if isinstance(mean_p, (int, float))
        else str(mean_p)
    )
    med_s = (
        f"{100 * med_p:.2f}" if isinstance(med_p, (int, float)) else str(med_p)
    )
    total_s = (
        f"{total_usd:.2f}"
        if isinstance(total_usd, (int, float))
        else str(total_usd)
    )
    mcpt_p_s = f"{mcpt_p:.4f}" if isinstance(mcpt_p, (int, float)) else str(mcpt_p)
    status_label = (
        "healthy window"
        if status == "healthy"
        else ("candidate window" if status == "candidate" else status)
    )
    p_note = (
        f" (MCPT pass_5pct, p={mcpt_p_s})"
        if mcpt_pass is True
        else ""
    )

    return f"""# XSP backtest packet: {variant_id}

## Target

CeminiSuite / xsp-killer — Lane A variant review

## Summary

Lane A backtest flagged `{variant_id}` as a **{status_label}**{p_note}.
Modeled premiums only — relative ranker, NOT a LIVE promotion.

| Field | Value |
|-------|-------|
| variant_id | `{variant_id}` |
| status / priority | {status} / {priority} |
| mode / source | {mode} / {source} |
| n_trades | {n_trades} |
| win% | {win_s} |
| mean net% | {mean_s} |
| median net% | {med_s} |
| total $ | {total_s} |
| MCPT p / pass@5% | {mcpt_p_s} / {mcpt_pass} |
| report | `{report_json}` |

## Body

### Why flagged

{reason}

### Disclaimer

Modeled option premiums from SPY OHLC (BS-lite). Not historical fills.
Relative ranker only — does NOT replace paper soak for LIVE promotion.
`LIVE_ENTRIES`/`LIVE_EXITS` untouched.

### Operator notes

- Packet is **staging only** under `.local/ops/xsp/packets/`.
- Human promote ritual: copy to `briefs/xsp-YYYY-MM-DD_<slug>.md` after review.
- Do NOT auto-ship to prod, wiki, or `briefs/`.

### Next steps

1. Confirm the window holds on a longer UW period / different seed.
2. If keep: promote to `briefs/` and run a paper soak before any LIVE change.
3. If noise: leave packet in place; no `briefs/` write.
"""


def write_packet(
    post: dict[str, Any],
    packets_dir: Path,
    *,
    day: date | None = None,
) -> Path:
    packets_dir.mkdir(parents=True, exist_ok=True)
    name = packet_filename(str(post.get("slug") or "variant"), day=day)
    path = packets_dir / name
    path.write_text(render_packet_markdown(post), encoding="utf-8")
    return path


def existing_packet_for_slug(packets_dir: Path, slug: str) -> Path | None:
    if not packets_dir.is_dir():
        return None
    for path in packets_dir.glob(f"*_{slug}.md"):
        return path
    for path in packets_dir.glob("*.md"):
        if path.stem.endswith(f"_{slug}") or path.stem == slug:
            return path
    return None
