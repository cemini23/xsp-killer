"""Nagus ops control-plane helpers for the Lane A backtest sensor.

Self-contained: no intel.core, no OSINT xsp_ops imports.
Filesystem brain + queue + staging packets under XSP_OPS_ROOT
(or .local/ops/xsp/).
"""

from __future__ import annotations

__all__ = ["emit_from_report"]


def __getattr__(name: str):
    if name == "emit_from_report":
        from xsp_killer.ops.emit import emit_from_report

        return emit_from_report
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
