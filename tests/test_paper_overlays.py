from datetime import datetime
from zoneinfo import ZoneInfo

from xsp_killer.paper_autoloop import (
    SpySnapshot,
    run_paper_tick,
    run_pc_cycle,
)
from xsp_killer.put_credit_paper import PcRules
from xsp_killer.uw_put_marks import PutCreditMarks
from xsp_killer.uw_shadow import build_market_tide_summary

ET = ZoneInfo("America/New_York")


def test_market_tide_summary_bias():
    payload = {
        "data": [
            {"net_call_premium": 100, "net_put_premium": 80, "timestamp": "t1"},
            {"net_call_premium": 50, "net_put_premium": 200, "timestamp": "t2"},
        ]
    }
    out = build_market_tide_summary(payload)
    assert out is not None
    assert out["bias"] == "put"
    assert out["n"] == 2


def test_paper_tick_attaches_overlays_without_veto(tmp_path, monkeypatch):
    overlays = {
        "shadow_only": True,
        "veto": False,
        "tipseeker": {"tickers": {"SPY": {"king_strike": 775.0}}},
        "iv_rank": {"iv_rank_1y": 22.0},
        "market_tide": {"bias": "call"},
    }
    monkeypatch.setattr(
        "xsp_killer.paper_autoloop.load_paper_overlays", lambda: overlays
    )
    result = run_paper_tick(
        now_et=datetime(2026, 8, 16, 12, 0, tzinfo=ET),
        snapshot=SpySnapshot(close=776.34, ma20=756.20, rv20=0.12, asof="2026-08-14"),
        run_lane_a=False,
        pc_sleeves=[],
        heartbeat_path=tmp_path / "hb.json",
        log_path=tmp_path / "tick.jsonl",
    )
    assert result["overlays"]["tipseeker"]["tickers"]["SPY"]["king_strike"] == 775.0
    assert result["overlays"]["veto"] is False
    assert result["live_untouched"] is True


def test_pc_cycle_uses_injected_uw_marks(tmp_path):
    marks = PutCreditMarks(
        short_mid=3.5,
        long_mid=1.5,
        net_credit=2.0,
        expiration="2026-08-28",
        source="uw_spy_put",
        stale=False,
    )
    state = {"paper_positions": {}, "closed": []}
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=SpySnapshot(close=776.34, ma20=756.20, rv20=0.12, asof="2026-08-14"),
        now_et=datetime(2026, 8, 17, 15, 50, tzinfo=ET),
        log_path=tmp_path / "pc.jsonl",
        live_marks=True,
        mark_fn=lambda **kwargs: marks,
    )
    pos = next(iter(state["paper_positions"].values()))
    assert pos["entry_credit"] == 2.0
    assert pos["pricing_fidelity"] == "uw_spy_put"
    assert out["overlays_veto"] is False
