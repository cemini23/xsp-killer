#!/usr/bin/env python3
"""One unattended paper cycle. LIVE_* forced false. No broker orders."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

from xsp_killer.paper_autoloop import ET, run_paper_tick  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Unattended paper tick (LIVE off)")
    p.add_argument("--at-et", default=None, help="Override ET time ISO or HH:MM")
    p.add_argument("--no-lane-a", action="store_true")
    p.add_argument("--pc-only", action="store_true")
    args = p.parse_args()

    now_et = None
    if args.at_et:
        raw = args.at_et.strip()
        if "T" in raw or ("-" in raw and len(raw) > 8):
            now_et = datetime.fromisoformat(raw)
            if now_et.tzinfo is None:
                now_et = now_et.replace(tzinfo=ET)
        else:
            today = datetime.now(ET).date()
            now_et = datetime.combine(
                today, datetime.strptime(raw, "%H:%M").time(), tzinfo=ET
            )

    result = run_paper_tick(
        now_et=now_et,
        run_lane_a=not (args.no_lane_a or args.pc_only),
    )
    print(json.dumps({k: result[k] for k in result if k != "sleeves"}, indent=2))
    for name, sleeve in (result.get("sleeves") or {}).items():
        print(f"{name}: {sleeve.get('event') or sleeve.get('ok')} {sleeve.get('reason') or sleeve.get('error') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
