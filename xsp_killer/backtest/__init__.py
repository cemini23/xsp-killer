"""Lane A historical backtest — rank variants on modeled option paths.

Read-only research tool. Never enables LIVE_ENTRIES / LIVE_EXITS.
Premium paths are synthesized from underlying OHLC (not historical fills).
"""

from __future__ import annotations

__all__ = [
    "load_bars",
    "run_backtest",
    "run_variant_sweep",
    "build_report",
    "mcpt",
]

from xsp_killer.backtest.bars import load_bars
from xsp_killer.backtest.engine import run_backtest
from xsp_killer.backtest.report import build_report, mcpt
from xsp_killer.backtest.sweep import run_variant_sweep
