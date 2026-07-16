#!/usr/bin/env python3
"""Centered 28 DTE ATM factorial optimizer for Lane A.

Read-only. Never flips LIVE_ENTRIES / LIVE_EXITS.
Offline: ``python scripts/optimize_lane_a.py --mode fixture``
UW:     ``python scripts/optimize_lane_a.py --mode uw --period 2y --mcpt -v``
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xsp_killer.backtest.bars import load_bars  # noqa: E402
from xsp_killer.backtest.optimize import (  # noqa: E402
    GridBudgetError,
    print_optimize_table,
    run_optimize,
    write_optimize_report,
)

logger = logging.getLogger("xsp_killer.optimize_cli")

_DEFAULT_TIPDROP = Path(r"C:\Users\Owner\institutional-shadow")


def _load_uw_key_from_tipdrop() -> None:
    """Load UNUSUAL_WHALES_API_KEY from tipdrop .env if env unset.

    Never logs or prints the key value — only that it was loaded.
    """
    existing = os.getenv("UNUSUAL_WHALES_API_KEY", "").strip()
    if existing:
        return

    tipdrop = os.getenv("XSP_UW_TIPDROP_ROOT", "").strip()
    root = Path(tipdrop) if tipdrop else _DEFAULT_TIPDROP
    env_path = root / ".env"
    if not env_path.is_file():
        logger.debug("tipdrop .env not found at %s", env_path)
        return

    try:
        text = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("could not read tipdrop .env: %s", exc)
        return

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key != "UNUSUAL_WHALES_API_KEY":
            continue
        val = val.strip().strip("'").strip('"')
        if val:
            os.environ["UNUSUAL_WHALES_API_KEY"] = val
            logger.info("loaded UNUSUAL_WHALES_API_KEY from tipdrop .env")
            # intentionally never log the value
            return
    logger.debug("UNUSUAL_WHALES_API_KEY not found in tipdrop .env")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Centered factorial optimize around 28 DTE ATM (UW or fixture). "
            "Train/holdout split + MCPT on top-K. Does not touch LIVE_* or "
            "config/lane_a_variants.yaml."
        )
    )
    p.add_argument(
        "--mode",
        choices=("fixture", "uw"),
        default="fixture",
        help="Data source (uw fails open to fixture without key)",
    )
    p.add_argument("--period", default="2y", help="UW history period (e.g. 2y, 1y)")
    p.add_argument("--start", default=None, help="Inclusive start date YYYY-MM-DD")
    p.add_argument("--end", default=None, help="Inclusive end date YYYY-MM-DD")
    p.add_argument("--ticker", default="SPY")
    p.add_argument(
        "--split-frac",
        type=float,
        default=0.6,
        help="Train fraction of bar date-range (default 0.6)",
    )
    p.add_argument(
        "--min-trades",
        type=int,
        default=8,
        help="Min holdout trades for promote-shape recommendation",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Top-K by holdout mean get MCPT",
    )
    p.add_argument(
        "--mcpt",
        action="store_true",
        help="Run MCPT-lite sign-flip on top-K holdout paths",
    )
    p.add_argument(
        "--mcpt-perm",
        type=int,
        default=1000,
        help="MCPT permutations (default 1000)",
    )
    p.add_argument(
        "--refine",
        action="store_true",
        help="After base grid, run ±neighbor cells around top survivors",
    )
    p.add_argument(
        "--allow-large",
        action="store_true",
        help="Allow grid size > 80 (budget guard off)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / "backtest",
        help="Output directory for optimize_*.json + .md",
    )
    p.add_argument("--iv", type=float, default=0.18, help="IV seed for BS-lite")
    p.add_argument(
        "--no-bs",
        action="store_true",
        help="Use estimate_fallback_premium instead of BS-lite",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.mode == "uw":
        _load_uw_key_from_tipdrop()

    bars, source = load_bars(
        mode=args.mode,
        interval="1d",
        ticker=args.ticker,
        period=args.period,
        start=args.start,
        end=args.end,
    )
    if source == "fixture_fallback":
        print(
            "WARN: --mode uw fell back to fixtures (no key / provider / empty). "
            "Results are offline-synthetic, not UW history.",
            file=sys.stderr,
        )

    try:
        payload = run_optimize(
            bars,
            split_frac=float(args.split_frac),
            min_trades=int(args.min_trades),
            top_k=int(args.top_k),
            run_mcpt=bool(args.mcpt),
            n_perm=int(args.mcpt_perm),
            allow_large=bool(args.allow_large),
            refine=bool(args.refine),
            iv_seed=float(args.iv),
            use_bs=not args.no_bs,
            source=source,
            mode=args.mode,
            meta={
                "ticker": args.ticker,
                "period": args.period,
                "start": args.start,
                "end": args.end,
                "iv_seed": args.iv,
                "use_bs": not args.no_bs,
                "n_bars": len(bars),
                "allow_large": bool(args.allow_large),
                "refine": bool(args.refine),
            },
        )
    except GridBudgetError as exc:
        logger.error("%s", exc)
        return 2

    json_path, md_path = write_optimize_report(payload, args.out)
    print_optimize_table(payload)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
