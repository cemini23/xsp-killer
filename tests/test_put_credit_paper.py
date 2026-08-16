from datetime import date, datetime

from zoneinfo import ZoneInfo

from xsp_killer.put_credit_paper import (
    PcRules,
    evaluate_pc_exits,
    evaluate_pc_gates,
    replay_pc_daily,
)

ET = ZoneInfo("America/New_York")


def test_gates_skip_friday_and_fomc_and_below_ma():
    rules = PcRules()
    friday = datetime(2026, 1, 23, 15, 50, tzinfo=ET)  # Friday
    assert evaluate_pc_gates(
        now_et=friday,
        close=600.0,
        ma20=590.0,
        rules=rules,
    ).allowed is False

    fomc_eve = datetime(2026, 1, 27, 15, 50, tzinfo=ET)  # day before 1/28
    g = evaluate_pc_gates(
        now_et=fomc_eve,
        close=600.0,
        ma20=590.0,
        rules=rules,
    )
    assert g.allowed is False
    assert g.reason == "fomc_window"

    below = datetime(2026, 1, 21, 15, 50, tzinfo=ET)  # Wednesday
    g = evaluate_pc_gates(
        now_et=below,
        close=580.0,
        ma20=590.0,
        rules=rules,
    )
    assert g.allowed is False
    assert g.reason == "below_ma20"

    ok = datetime(2026, 1, 21, 15, 50, tzinfo=ET)
    g = evaluate_pc_gates(
        now_et=ok,
        close=600.0,
        ma20=590.0,
        rules=rules,
    )
    assert g.allowed is True


def test_exits_velocity_dma_friday():
    rules = PcRules(velocity_pct=0.76, max_hold_sessions=5)
    pos = {
        "entry_credit": 3.0,
        "width_points": 5.0,
        "entry_date": "2026-01-20",
        "mark_value": 0.70,
        "above_ma20": True,
    }
    assert evaluate_pc_exits(
        pos,
        now_et=datetime(2026, 1, 21, 15, 50, tzinfo=ET),
        sessions_held=1,
        rules=rules,
    ) == "velocity_76"

    pos["mark_value"] = 2.5
    pos["above_ma20"] = False
    assert evaluate_pc_exits(
        pos,
        now_et=datetime(2026, 1, 21, 15, 50, tzinfo=ET),
        sessions_held=1,
        rules=rules,
    ) == "dma_break"

    pos["above_ma20"] = True
    assert evaluate_pc_exits(
        pos,
        now_et=datetime(2026, 1, 23, 15, 50, tzinfo=ET),
        sessions_held=3,
        rules=rules,
    ) == "friday_flatten"


def test_replay_skips_below_ma_and_friday():
    import pandas as pd

    days = pd.bdate_range("2026-01-05", periods=40, tz="America/New_York")
    closes = [100.0 + i * 0.4 for i in range(len(days))]
    # Dip below MA in the middle
    closes[25] = closes[24] - 8.0
    df = pd.DataFrame(
        {
            "date": [d.date() for d in days],
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(days),
        }
    )
    result = replay_pc_daily(df, PcRules())
    assert result["n_entries"] >= 1
    assert all(t["entry_date"] != date(2026, 1, 23).isoformat() for t in result["trades"])
    assert result["n_blocked_below_ma"] >= 1
