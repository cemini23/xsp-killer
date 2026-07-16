#!/usr/bin/env python3
"""Nagus backtest sensor — re-emit ops state from an existing Lane A report.

Does **not** run the backtest engine. Reads report JSON and lands brain /
posts / queue / packets under ``$XSP_OPS_ROOT`` (or ``.local/ops/xsp/``).

Examples::

    python3 scripts/nagus_backtest_sensor.py --from-latest
    python3 scripts/nagus_backtest_sensor.py --report \\
        reports/backtest/lane_a_bt_....json
    python3 scripts/nagus_backtest_sensor.py --from-latest --dry-run
    XSP_OPS_ROOT=/tmp/soak python3 scripts/nagus_backtest_sensor.py \\
        --from-latest
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xsp_killer.ops.emit import emit_from_report  # noqa: E402
from xsp_killer.ops.paths import resolve_ops_root  # noqa: E402

logger = logging.getLogger("xsp_killer.nagus_backtest_sensor")

DEFAULT_OUT_DIR = ROOT / "reports" / "backtest"


def find_latest_report(out_dir: Path) -> Path | None:
    """Return newest ``lane_a_bt_*.json`` under out_dir, or None."""
    if not out_dir.is_dir():
        return None
    candidates = sorted(
        out_dir.glob("lane_a_bt_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Emit Nagus ops state from a Lane A backtest report JSON "
            "(no engine re-run)."
        )
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Path to a lane_a_bt_*.json report",
    )
    src.add_argument(
        "--from-latest",
        action="store_true",
        help="Use newest lane_a_bt_*.json under --out-dir",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Report directory for --from-latest (default: reports/backtest)",
    )
    p.add_argument(
        "--ops-root",
        type=Path,
        default=None,
        help="Override ops root (else XSP_OPS_ROOT or .local/ops/xsp)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute emit plan without durable ops writes",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.report is not None:
        report_path = Path(args.report)
        if not report_path.is_file():
            logger.error("report not found: %s", report_path)
            return 2
    else:
        report_path = find_latest_report(Path(args.out_dir))
        if report_path is None:
            logger.error(
                "no lane_a_bt_*.json under %s",
                args.out_dir,
            )
            return 2

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to load report (fail-open): %s", exc)
        return 0

    if not isinstance(payload, dict):
        logger.warning("report is not a JSON object (fail-open): %s", report_path)
        return 0

    md_path = report_path.with_suffix(".md")
    if not md_path.is_file():
        md_path = None

    ops_root = Path(args.ops_root) if args.ops_root else resolve_ops_root()

    try:
        summary = emit_from_report(
            payload,
            report_json=report_path,
            report_md=md_path,
            root=ops_root,
            dry_run=bool(args.dry_run),
        )
        print(f"[nagus] report={report_path}")
        print(f"[nagus] {summary}")
    except Exception as exc:  # fail-open: never block the pipeline
        logger.warning("nagus emit failed (non-fatal): %s", exc)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
