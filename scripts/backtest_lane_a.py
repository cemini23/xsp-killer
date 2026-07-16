#!/usr/bin/env python3
"""Lane A historical backtest CLI — rank variants on modeled option paths.

Read-only. Never flips LIVE_ENTRIES / LIVE_EXITS.
Offline: ``python3 scripts/backtest_lane_a.py --mode fixture``
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xsp_killer.backtest.bars import load_bars  # noqa: E402
from xsp_killer.backtest.report import (  # noqa: E402
    build_report,
    print_ranking_table,
    write_report,
)
from xsp_killer.backtest.sweep import parse_sweep_axes, run_variant_sweep  # noqa: E402

logger = logging.getLogger("xsp_killer.backtest_cli")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Backtest Lane A variants on SPY OHLC (fixture or UW). "
            "Modeled premiums — relative ranker only; does not replace paper soak."
        )
    )
    p.add_argument(
        "--mode",
        choices=("fixture", "uw"),
        default="fixture",
        help="Data source (uw fails open to fixture without key)",
    )
    p.add_argument(
        "--variants",
        default="active",
        help="active | all | comma-separated variant ids",
    )
    p.add_argument(
        "--sweep",
        default="",
        help="Comma axes: dte,strike,tp,sl,regime,swing (one-axis micro-sweeps)",
    )
    p.add_argument(
        "--mcpt",
        action="store_true",
        help="Append MCPT-lite sign-flip p-values",
    )
    p.add_argument("--mcpt-perm", type=int, default=500, help="MCPT permutations")
    p.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / "backtest",
        help="Output directory for json+md",
    )
    p.add_argument("--start", default=None, help="Inclusive start date YYYY-MM-DD")
    p.add_argument("--end", default=None, help="Inclusive end date YYYY-MM-DD")
    p.add_argument("--period", default="2y", help="UW history period (e.g. 2y, 1y)")
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--iv", type=float, default=0.18, help="IV seed for BS-lite")
    p.add_argument(
        "--no-bs",
        action="store_true",
        help="Use estimate_fallback_premium instead of BS-lite",
    )
    p.add_argument(
        "--no-baseline",
        action="store_true",
        help="Skip injecting v2_baseline_prod",
    )
    p.add_argument(
        "--nagus",
        action="store_true",
        help=(
            "Emit Nagus ops state (brain/posts/queue/packets) "
            "after writing the report"
        ),
    )
    p.add_argument(
        "--nagus-dry-run",
        action="store_true",
        help="Compute + print Nagus emit plan without durable ops writes",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        axes = parse_sweep_axes(args.sweep or None)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

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

    results = run_variant_sweep(
        bars,
        variants=args.variants,
        sweep_axes=axes or None,
        include_baseline=not args.no_baseline,
        iv_seed=float(args.iv),
        use_bs=not args.no_bs,
        source=source,
    )

    payload = build_report(
        results,
        run_mcpt=bool(args.mcpt),
        n_perm=int(args.mcpt_perm),
        mode=args.mode,
        source=source,
        meta={
            "ticker": args.ticker,
            "period": args.period,
            "start": args.start,
            "end": args.end,
            "iv_seed": args.iv,
            "use_bs": not args.no_bs,
            "sweep_axes": axes,
            "n_bars": len(bars),
            "variants_arg": args.variants,
        },
    )

    out_dir = args.out
    json_path, md_path = write_report(payload, out_dir)
    print_ranking_table(payload)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")

    if args.nagus or args.nagus_dry_run:
        try:
            from xsp_killer.ops.emit import emit_from_report

            summary = emit_from_report(
                payload,
                report_json=json_path,
                report_md=md_path,
                dry_run=bool(args.nagus_dry_run),
            )
            print(f"[nagus] {summary}")
        except Exception as exc:  # fail-open: report already written
            logger.warning("nagus emit failed (non-fatal): %s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
