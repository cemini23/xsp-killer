#!/usr/bin/env python3
"""Robinhood MCP readiness check — no orders."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

from xsp_killer.rh_broker import (  # noqa: E402
    fetch_robinhood_option_positions,
    rh_mcp_enabled,
    rh_poll_enabled,
    rh_read_enabled,
)
from xsp_killer.robinhood_mcp import (  # noqa: E402
    RhMcpConfig,
    live_exits_enabled,
    pinned_account_on_token,
    rh_mcp_enabled as mcp_flag,
)


def main() -> int:
    p = argparse.ArgumentParser(description="XSP Killer RH MCP health check")
    p.add_argument(
        "--compare-legacy",
        action="store_true",
        help="Also poll robin_stocks when RH_USERNAME set (parallel compare)",
    )
    args = p.parse_args()

    cfg = RhMcpConfig.load()
    print("=== XSP Killer Robinhood readiness ===")
    print(f"rh_read_enabled: {rh_read_enabled()}")
    print(f"XSP_LANE_A_RH_MCP: {rh_mcp_enabled()}")
    print(f"XSP_LANE_A_RH_POLL: {rh_poll_enabled()}")
    print(f"XSP_LANE_A_LIVE_EXITS: {live_exits_enabled(config=cfg)}")
    print(f"token_path exists: {cfg.token_path.is_file()} ({cfg.token_path})")
    print(f"agentic_account_id set: {bool(cfg.agentic_account_id)}")

    if not rh_read_enabled() and not args.compare_legacy:
        print("\nPaper mode — no RH read path enabled (expected).")
        print("Enable XSP_LANE_A_RH_MCP=true after desktop OAuth + token export.")
        return 0

    if rh_mcp_enabled():
        pin_ok, pin_reason = pinned_account_on_token()
        print(f"pinned_account_on_token: {pin_ok} ({pin_reason})")
        if not pin_ok and cfg.agentic_account_id:
            print("WARNING: pin/token mismatch — do not enable LIVE_*")

        rows, err = fetch_robinhood_option_positions()
        print(f"\nMCP positions: {len(rows)}")
        if err:
            print(f"MCP error: {err}")
        else:
            from xsp_killer.data_hazards import fusion_tier
            from xsp_killer.robinhood_mcp import last_mcp_fetch_confidence

            wrap = last_mcp_fetch_confidence()
            if wrap:
                tier = fusion_tier(float(wrap.get("confidence") or 0.0))
                print(
                    f"MCP read confidence: {wrap.get('confidence')} "
                    f"(tier={tier}, hazard={wrap.get('hazard_class')})"
                )
            sample = [
                {
                    "chain": r.get("chain_symbol"),
                    "strike": r.get("strike_price"),
                    "qty": r.get("quantity"),
                    "_source": r.get("_source"),
                }
                for r in rows[:3]
            ]
            print(json.dumps(sample, indent=2))

    if args.compare_legacy and rh_poll_enabled():
        os.environ.setdefault("XSP_LANE_A_RH_MCP", "false")
        from xsp_killer.rh_broker import _fetch_via_robin_stocks

        legacy, err = _fetch_via_robin_stocks()
        print(f"\nLegacy robin_stocks positions: {len(legacy)}")
        if err:
            print(f"Legacy error: {err}")

    return 0 if mcp_flag() else 0


if __name__ == "__main__":
    raise SystemExit(main())
