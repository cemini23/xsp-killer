from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from xsp_killer.paper_autoloop import SpySnapshot, run_pc_cycle
from xsp_killer.put_credit_paper import PcRules, evaluate_pc_exits
from xsp_killer.uw_put_marks import (
    PutCreditMarks,
    _marks_from_puts,
    accept_mark_value,
)

ET = ZoneInfo("America/New_York")


def test_marks_from_puts_reject_nonpositive_credit():
    puts = pd.DataFrame(
        {
            "strike": [770.0, 775.0],
            "bid": [4.0, 1.0],
            "ask": [4.2, 1.2],
            "lastPrice": [4.1, 1.1],
        }
    )
    assert _marks_from_puts(puts, 775.0, 770.0, "2026-08-28", "uw_spy_put") is None


def test_marks_from_puts_reject_far_strike():
    puts = pd.DataFrame(
        {
            "strike": [700.0, 800.0],
            "bid": [2.0, 4.0],
            "ask": [2.2, 4.2],
            "lastPrice": [2.1, 4.1],
        }
    )
    assert _marks_from_puts(puts, 775.0, 770.0, "2026-08-28", "uw_spy_put") is None


def test_accept_mark_value_rejects_zero_and_same_session_velocity():
    assert accept_mark_value(
        entry=2.33, last=2.33, new=0.0, dte_left=14, sessions_held=0
    ) == 2.33
    assert accept_mark_value(
        entry=2.33, last=2.33, new=0.40, dte_left=14, sessions_held=0
    ) == 2.33
    assert accept_mark_value(
        entry=2.00, last=2.00, new=1.80, dte_left=7, sessions_held=0
    ) == 1.80


def test_zero_uw_mark_does_not_velocity_exit(tmp_path):
    state = {
        "paper_positions": {
            "pc-1": {
                "entry_credit": 2.33,
                "width_points": 5.0,
                "entry_date": "2026-08-17",
                "short_strike": 775.0,
                "long_strike": 770.0,
                "mark_value": 2.33,
                "above_ma20": True,
                "sessions_held": 0,
                "dte": 14,
                "iv": 0.13,
            }
        },
        "closed": [],
        "last_entry_date": "2026-08-17",
    }
    dead = PutCreditMarks(
        short_mid=0.0,
        long_mid=0.0,
        net_credit=0.0,
        expiration="2026-08-28",
        source="uw_spy_put",
    )
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=SpySnapshot(close=772.67, ma20=757.73, rv20=0.13, asof="2026-08-17"),
        now_et=datetime(2026, 8, 17, 15, 50, tzinfo=ET),
        log_path=tmp_path / "pc.jsonl",
        live_marks=True,
        mark_fn=lambda **kwargs: dead,
    )
    assert out["event"] == "pc_hold"
    pos = state["paper_positions"]["pc-1"]
    assert pos["mark_value"] == 2.33
    assert state["closed"] == []


def test_same_day_reentry_blocked(tmp_path):
    state = {
        "paper_positions": {},
        "closed": [{"entry_date": "2026-08-17", "void": False}],
        "last_entry_date": "2026-08-17",
    }
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=SpySnapshot(close=772.67, ma20=757.73, rv20=0.13, asof="2026-08-17"),
        now_et=datetime(2026, 8, 17, 15, 50, tzinfo=ET),
        log_path=tmp_path / "pc.jsonl",
    )
    assert out["event"] == "pc_entry_skip"
    assert out["reason"] == "already_entered_today"
    assert state["paper_positions"] == {}


def test_marks_from_puts_accepts_positive_credit():
    puts = pd.DataFrame(
        {
            "strike": [770.0, 775.0],
            "bid": [1.9, 3.8],
            "ask": [2.1, 4.2],
            "lastPrice": [2.0, 4.0],
        }
    )
    marks = _marks_from_puts(puts, 775.0, 770.0, "2026-08-28", "uw_spy_put")
    assert marks is not None
    assert marks.net_credit == 2.0


def test_exits_ignore_stale_zero_mark():
    pos = {
        "entry_credit": 2.33,
        "mark_value": 0.0,
        "above_ma20": True,
        "dte": 14,
    }
    assert (
        evaluate_pc_exits(
            pos,
            now_et=datetime(2026, 8, 17, 15, 50, tzinfo=ET),
            sessions_held=0,
            rules=PcRules(),
        )
        is None
    )


def test_valid_uw_mark_updates_hold(tmp_path):
    good = PutCreditMarks(
        short_mid=3.0,
        long_mid=1.2,
        net_credit=1.8,
        expiration="2026-08-28",
        source="uw_spy_put",
    )
    state = {
        "paper_positions": {
            "pc-1": {
                "entry_credit": 2.00,
                "width_points": 5.0,
                "entry_date": "2026-08-17",
                "short_strike": 775.0,
                "long_strike": 770.0,
                "mark_value": 2.00,
                "above_ma20": True,
                "sessions_held": 0,
                "last_monitor_date": "2026-08-17",
                "dte": 7,
                "iv": 0.13,
            }
        },
        "closed": [],
        "last_entry_date": "2026-08-17",
    }
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=SpySnapshot(close=772.67, ma20=757.73, rv20=0.13, asof="2026-08-17"),
        now_et=datetime(2026, 8, 17, 15, 50, tzinfo=ET),
        log_path=tmp_path / "pc.jsonl",
        live_marks=True,
        mark_fn=lambda **kwargs: good,
    )
    assert out["event"] == "pc_hold"
    assert state["paper_positions"]["pc-1"]["mark_value"] == 1.8
    assert state["paper_positions"]["pc-1"]["pricing_fidelity"] == "uw_spy_put"


def test_velocity_exit_writes_pnl(tmp_path):
    state = {
        "paper_positions": {
            "pc-1": {
                "entry_credit": 3.0,
                "width_points": 5.0,
                "entry_date": "2026-08-17",
                "short_strike": 775.0,
                "long_strike": 770.0,
                "mark_value": 0.50,
                "above_ma20": True,
                "sessions_held": 1,
                "dte": 14,
                "iv": 0.12,
            }
        },
        "closed": [],
    }
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=SpySnapshot(
            close=776.34, ma20=756.20, rv20=0.12, asof="2026-08-18", mark_value=0.50
        ),
        now_et=datetime(2026, 8, 18, 15, 50, tzinfo=ET),
        log_path=tmp_path / "pc.jsonl",
    )
    assert out["event"] == "pc_exit"
    assert state["closed"][0]["pnl_usd"] is not None
    assert state["closed"][0]["pnl_usd"] > 0


def test_nan_close_does_not_dma_exit(tmp_path):
    state = {
        "paper_positions": {
            "pc-2026-08-17-775": {
                "position_id": "pc-2026-08-17-775",
                "entry_credit": 1.975,
                "width_points": 5.0,
                "entry_date": "2026-08-17",
                "short_strike": 775.0,
                "long_strike": 770.0,
                "mark_value": 2.075,
                "above_ma20": True,
                "sessions_held": 0,
                "last_monitor_date": "2026-08-17",
                "dte": 7,
                "iv": 0.13,
            }
        },
        "closed": [],
        "last_entry_date": "2026-08-17",
    }
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=SpySnapshot(close=float("nan"), ma20=756.94, rv20=0.13, asof="2026-08-17"),
        now_et=datetime(2026, 8, 18, 0, 4, tzinfo=ET),
        log_path=tmp_path / "pc.jsonl",
    )
    assert out["event"] == "pc_hold"
    pos = state["paper_positions"]["pc-2026-08-17-775"]
    assert pos["above_ma20"] is True
    assert pos["sessions_held"] == 0
    assert state["closed"] == []


def test_finite_history_drops_nan_last_bar():
    import math

    import pandas as pd

    from xsp_killer.paper_autoloop import _finite_daily_history

    idx = pd.bdate_range("2026-07-20", periods=22)
    closes = list(range(750, 772))
    hist = pd.DataFrame({"Close": closes}, index=idx)
    hist.loc[hist.index[-1], "Close"] = float("nan")
    work = _finite_daily_history(hist, ma_period=20)
    assert math.isfinite(float(work["Close"].iloc[-1]))
    assert len(work) == 21
