import sqlite3
from pathlib import Path

from xsp_killer.tipseeker_shadow import load_latest_tipseeker


def _seed(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY,
            ts_et TEXT NOT NULL,
            ticker TEXT NOT NULL,
            spot REAL,
            king_strike REAL,
            king_gex REAL,
            floor_strike REAL,
            ceiling_strike REAL,
            gatekeeper_strike REAL,
            total_gex REAL,
            nodes_json TEXT
        )
        """
    )
    rows = [
        ("4:00 AM ET", "SPY", 770.0, 770.0, 1e9, 765.0, 775.0, 772.0, 1e9, "{}"),
        ("4:49 AM ET", "SPY", 776.34, 775.0, 2e9, 775.0, 780.0, None, 3e9, "{}"),
        ("4:49 AM ET", "SPXW", 7785.76, 7790.0, 4e9, 7750.0, 7790.0, 7780.0, -1e9, "{}"),
        ("4:49 AM ET", "QQQ", 731.07, 735.0, 1e9, 730.0, 735.0, None, 1e9, "{}"),
    ]
    con.executemany(
        """
        INSERT INTO snapshots (
            ts_et, ticker, spot, king_strike, king_gex,
            floor_strike, ceiling_strike, gatekeeper_strike, total_gex, nodes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    con.close()


def test_load_latest_tipseeker_picks_newest_spy_and_spxw(tmp_path):
    db = tmp_path / "tipseeker.db"
    _seed(db)
    out = load_latest_tipseeker(path=db)
    assert out is not None
    assert out["shadow_only"] is True
    assert out["veto"] is False
    spy = out["tickers"]["SPY"]
    assert spy["king_strike"] == 775.0
    assert spy["floor_strike"] == 775.0
    assert spy["ceiling_strike"] == 780.0
    assert spy["ts_et"] == "4:49 AM ET"
    assert out["tickers"]["SPXW"]["king_strike"] == 7790.0
    assert "QQQ" not in out["tickers"]


def test_load_latest_tipseeker_missing_db_is_none(tmp_path):
    assert load_latest_tipseeker(path=tmp_path / "nope.db") is None
