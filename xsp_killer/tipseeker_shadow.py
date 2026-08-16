"""Read TipSeeker sqlite snapshots — log-only, no extra UW calls.

Never vetoes. Never places. TipSeeker is a map, not a signal.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path(r"C:\Users\Owner\institutional-shadow\data_store\tipseeker.db")
_WATCH = ("SPY", "SPXW")


def _db_path(path: Path | None = None) -> Path:
    raw = os.getenv("XSP_TIPSEEKER_DB", "").strip()
    if path is not None:
        return path
    if raw:
        return Path(raw)
    return _DEFAULT_DB


def load_latest_tipseeker(
    path: Path | None = None,
    tickers: tuple[str, ...] = _WATCH,
) -> dict[str, Any] | None:
    db = _db_path(path)
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        out: dict[str, Any] = {}
        for ticker in tickers:
            row = con.execute(
                """
                SELECT ts_et, ticker, spot, king_strike, king_gex,
                       floor_strike, ceiling_strike, gatekeeper_strike, total_gex
                FROM snapshots
                WHERE ticker = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (ticker,),
            ).fetchone()
            if row is None:
                continue
            out[ticker] = {
                "ts_et": row["ts_et"],
                "spot": row["spot"],
                "king_strike": row["king_strike"],
                "king_gex": row["king_gex"],
                "floor_strike": row["floor_strike"],
                "ceiling_strike": row["ceiling_strike"],
                "gatekeeper_strike": row["gatekeeper_strike"],
                "total_gex": row["total_gex"],
            }
        con.close()
    except Exception:
        return None
    if not out:
        return None
    return {
        "shadow_only": True,
        "veto": False,
        "source": "tipseeker.db",
        "tickers": out,
    }
