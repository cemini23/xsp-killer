import os
from datetime import datetime
from zoneinfo import ZoneInfo

from xsp_killer.paper_autoloop import (
    SpySnapshot,
    force_paper_only_env,
    run_paper_tick,
    run_pc_cycle,
)
from xsp_killer.put_credit_paper import PcRules

ET = ZoneInfo("America/New_York")


def _snap() -> SpySnapshot:
    return SpySnapshot(close=776.34, ma20=756.20, rv20=0.12, asof="2026-08-14")


def test_force_paper_only_env_clears_live_flags(monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_ENTRIES", "true")
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    force_paper_only_env()
    assert os.environ["XSP_LANE_A_LIVE_ENTRIES"] == "false"
    assert os.environ["XSP_LANE_A_LIVE_EXITS"] == "false"
    assert os.environ["XSP_LANE_A_PAPER_ENTRY"] == "true"


def test_pc_cycle_skips_weekend_without_opening(tmp_path):
    state = {"paper_positions": {}, "closed": []}
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=_snap(),
        now_et=datetime(2026, 8, 16, 15, 50, tzinfo=ET),
        log_path=tmp_path / "pc.jsonl",
    )
    assert out["event"] == "pc_entry_skip"
    assert out["reason"] == "weekend"
    assert state["paper_positions"] == {}


def test_pc_cycle_opens_when_gates_pass(tmp_path):
    state = {"paper_positions": {}, "closed": []}
    out = run_pc_cycle(
        rules=PcRules(require_window=False),
        state=state,
        snapshot=_snap(),
        now_et=datetime(2026, 8, 17, 15, 50, tzinfo=ET),  # Monday
        log_path=tmp_path / "pc.jsonl",
    )
    assert out["event"] == "pc_entry"
    assert out["allowed"] is True
    assert len(state["paper_positions"]) == 1
    pos = next(iter(state["paper_positions"].values()))
    assert pos["entry_credit"] > 0
    assert pos["short_strike"] > pos["long_strike"]


def test_pc_cycle_exits_on_velocity(tmp_path):
    state = {
        "paper_positions": {
            "pc-1": {
                "entry_credit": 3.0,
                "width_points": 5.0,
                "entry_date": "2026-08-17",
                "entry_i": 0,
                "short_strike": 775.0,
                "long_strike": 770.0,
                "mark_value": 0.50,
                "above_ma20": True,
                "sessions_held": 1,
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
    assert out["reason"] == "velocity_76"
    assert state["paper_positions"] == {}
    assert len(state["closed"]) == 1


def test_paper_tick_keeps_going_if_one_sleeve_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_ENTRIES", "true")

    def boom(**kwargs):
        raise RuntimeError("lane_a_down")

    monkeypatch.setattr("xsp_killer.paper_autoloop._run_lane_a_paper", boom)
    monkeypatch.setattr(
        "xsp_killer.paper_autoloop.load_paper_overlays",
        lambda: {"shadow_only": True, "veto": False},
    )
    heartbeat = tmp_path / "paper-autoloop-latest.json"
    result = run_paper_tick(
        now_et=datetime(2026, 8, 16, 12, 0, tzinfo=ET),
        snapshot=_snap(),
        run_lane_a=True,
        pc_sleeves=[],
        heartbeat_path=heartbeat,
        log_path=tmp_path / "tick.jsonl",
    )
    assert os.environ["XSP_LANE_A_LIVE_ENTRIES"] == "false"
    assert result["live_untouched"] is True
    assert result["sleeves"]["lane_a"]["ok"] is False
    assert heartbeat.is_file()
