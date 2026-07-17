"""Friday flatten exit + Friday entry veto (history → Lane A rules)."""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from xsp_killer.lane_a_entry import EntryRules, run_paper_entry
from xsp_killer.lane_a_monitor import (
    DEFAULT_RULES,
    LaneAPosition,
    LaneRules,
    evaluate_exit_alerts,
)
from xsp_killer.lane_a_ta import TaSignal
from xsp_killer.robinhood_mcp import live_entries_enabled, live_exits_enabled

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]

# Thursday / Friday in 2026 (ET).
THU = datetime(2026, 7, 16, 15, 45, tzinfo=ET)
FRI_BEFORE = datetime(2026, 7, 17, 15, 44, tzinfo=ET)
FRI_AT = datetime(2026, 7, 17, 15, 45, tzinfo=ET)
FRI_AFTER = datetime(2026, 7, 17, 15, 50, tzinfo=ET)
# Tuesday close window — non-Friday entry still allowed when other gates pass.
TUE_WINDOW = datetime(2026, 7, 14, 15, 47, tzinfo=ET)

BASE_RULES = LaneRules(
    lane="A",
    dte_min=14,
    dte_max=60,
    exclude_expiry_month=("01",),
    chain_symbols=("SPX", "XSP"),
    stop_loss_pct=0.20,
    take_profit_pct=0.20,
    sell_eval_start_et=time(8, 0),
    sell_deadline_et=time(9, 30),
    no_sell_start_et=time(0, 0),
    no_sell_end_et=time(8, 0),
    require_upper_bb_for_take_profit=True,
    logic_version="xsp_lane_a_v2",
    friday_flatten_enabled=True,
    friday_flatten_et=time(15, 45),
)


def _pos(
    *,
    avg: float = 2.00,
    mark: float | None = 1.90,
    dte: int = 20,
) -> LaneAPosition:
    return LaneAPosition(
        position_id="paper:XSP:2026-07-18:6000",
        chain_symbol="XSP",
        option_type="call",
        strike=6000.0,
        expiration_date=__import__("datetime").date(2026, 7, 18),
        quantity=1.0,
        average_price=avg,
        mark_price=mark,
        dte=dte,
        entry_mid_premium=avg,
    )


def _mock_ta_entry_ok(monkeypatch):
    fake = TaSignal(
        signal="none",
        primary=None,
        confirm=None,
        entry_ok=False,
        exit_ok=False,
        upper_bb_touched=False,
        detail="not used in close_window_only",
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.evaluate_ta_signals",
        lambda rules, now_et=None: fake,
    )


def _stub_successful_entry(monkeypatch):
    """Pass all non-Friday gates so only calendar / window matter."""
    monkeypatch.setenv("XSP_LANE_A_PAPER_ENTRY", "true")
    _mock_ta_entry_ok(monkeypatch)

    def _regime():
        return "GREEN", True, None, None

    monkeypatch.setattr("xsp_killer.lane_a_entry.read_regime_detail", _regime)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.fetch_spy_ohlcv",
        lambda: (600.0, 595.0, 0.5, "2026-07-13"),
    )
    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spx_proxy", lambda: 6010.0)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_expiration",
        lambda rules, today=None, dte_pick="min", dte_target=None: __import__(
            "datetime"
        ).date(2026, 7, 31),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.fetch_spy_call_mark",
        lambda *a, **k: (2.45, False, 2.40, 2.50, False),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.compute_debit_spread_shadow",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_strike",
        lambda *args, **kwargs: (6010.0, 2.45, 0.52),
    )


def test_friday_1544_no_flatten():
    pos = _pos()
    alerts = evaluate_exit_alerts(pos, BASE_RULES, now_et=FRI_BEFORE)
    assert alerts == []


def test_friday_1545_fires_friday_flatten():
    pos = _pos()
    alerts = evaluate_exit_alerts(pos, BASE_RULES, now_et=FRI_AT)
    assert len(alerts) == 1
    assert alerts[0].exit_reason == "friday_flatten"
    assert "Friday flatten" in alerts[0].message
    assert "expiration" in alerts[0].message.lower()


def test_friday_after_clock_still_flattens():
    pos = _pos()
    alerts = evaluate_exit_alerts(pos, BASE_RULES, now_et=FRI_AFTER)
    assert [a.exit_reason for a in alerts] == ["friday_flatten"]


def test_thursday_1545_no_friday_flatten():
    pos = _pos()
    alerts = evaluate_exit_alerts(pos, BASE_RULES, now_et=THU)
    assert alerts == []


def test_sl_beats_friday_flatten():
    pos = _pos(avg=2.00, mark=1.50)  # -25% vs 20% SL
    alerts = evaluate_exit_alerts(pos, BASE_RULES, now_et=FRI_AT)
    assert len(alerts) == 1
    assert alerts[0].exit_reason == "stop_loss"


def test_friday_flatten_disabled_no_alert():
    rules = LaneRules(
        lane="A",
        dte_min=14,
        dte_max=60,
        exclude_expiry_month=("01",),
        chain_symbols=("SPX", "XSP"),
        stop_loss_pct=0.20,
        take_profit_pct=0.20,
        sell_eval_start_et=time(8, 0),
        sell_deadline_et=time(9, 30),
        no_sell_start_et=time(0, 0),
        no_sell_end_et=time(8, 0),
        require_upper_bb_for_take_profit=True,
        logic_version="xsp_lane_a_v2",
        friday_flatten_enabled=False,
        friday_flatten_et=time(15, 45),
    )
    assert evaluate_exit_alerts(_pos(), rules, now_et=FRI_AT) == []


def test_yaml_loads_friday_flatten_fields():
    rules = LaneRules.from_yaml(DEFAULT_RULES)
    assert rules.friday_flatten_enabled is True
    assert rules.friday_flatten_et == time(15, 45)


def test_paper_quantity_resolves_to_one():
    entry = EntryRules.from_yaml(DEFAULT_RULES)
    assert entry.quantity == 1.0
    assert entry.max_open_positions == 1


def test_live_flags_untouched(monkeypatch):
    monkeypatch.delenv("XSP_LANE_A_LIVE_ENTRIES", raising=False)
    monkeypatch.delenv("XSP_LANE_A_LIVE_EXITS", raising=False)
    assert live_entries_enabled() is False
    assert live_exits_enabled() is False


def test_friday_entry_veto(tmp_path, monkeypatch):
    _stub_successful_entry(monkeypatch)
    rules_path = tmp_path / "rules-close-window.yaml"
    rules_path.write_text(
        "ta:\n  entry:\n    mode: close_window_only\n",
        encoding="utf-8",
    )
    decision = run_paper_entry(
        rules_path=rules_path,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "paper.jsonl",
        now_et=FRI_AT,
        publish_intel=False,
    )
    assert decision.entered is False
    assert decision.skip_reason == "friday_no_entry"


def test_non_friday_entry_still_allowed(tmp_path, monkeypatch):
    _stub_successful_entry(monkeypatch)
    rules_path = tmp_path / "rules-close-window.yaml"
    rules_path.write_text(
        "ta:\n  entry:\n    mode: close_window_only\n",
        encoding="utf-8",
    )
    decision = run_paper_entry(
        rules_path=rules_path,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "paper.jsonl",
        now_et=TUE_WINDOW,
        publish_intel=False,
    )
    assert decision.entered is True
    assert decision.position is not None
    assert decision.position["quantity"] == 1.0
