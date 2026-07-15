"""Tests for XSP Lane A paper entry (no live yfinance/RH)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from xsp_killer.lane_a_entry import (
    EntryDecision,
    EntryRules,
    _bucket_skip_reason,
    _finalize_entry,
    _write_entry_telemetry_brief,
    already_entered_today,
    entry_logs_for_epoch,
    et_session_date,
    in_entry_window,
    is_et_trading_session,
    open_paper_positions,
    pick_cheapest_atm_strike,
    reap_expired_paper_positions,
    round_xsp_strike,
    run_paper_entry,
    scoreboard_entry_stale,
    summarize_entry_telemetry_from_logs,
    unique_et_sessions,
)
from xsp_killer.lane_a_monitor import LaneRules
from xsp_killer.lane_a_ta import TaSignal

ET = ZoneInfo("America/New_York")

ENTRY_RULES = EntryRules(
    window_start_et=time(15, 45),
    window_end_et=time(16, 0),
    prior_day_spy_positive=False,
    max_open_positions=1,
    quantity=1.0,
    enabled=True,
)

LANE_RULES = LaneRules(
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
)


def test_in_entry_window_weekday():
    inside = datetime(2026, 6, 16, 15, 47, tzinfo=ET)
    outside = datetime(2026, 6, 16, 15, 30, tzinfo=ET)
    weekend = datetime(2026, 6, 14, 15, 47, tzinfo=ET)
    assert in_entry_window(inside, ENTRY_RULES) is True
    assert in_entry_window(outside, ENTRY_RULES) is False
    assert in_entry_window(weekend, ENTRY_RULES) is False


def test_round_xsp_strike():
    assert round_xsp_strike(6012.3) == 6010.0


def test_pick_cheapest_atm_strike(monkeypatch):
    exp = date(2026, 7, 18)

    def _quote(strike, expiration):
        return (2.0 if strike == 601.0 else 2.5, 0.5)

    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spy_call_quote", _quote)
    strike, prem, _ = pick_cheapest_atm_strike(6012.0, exp, max_steps_from_atm=1)
    assert strike == 6010.0
    assert prem == 20.0


def test_open_paper_positions_filters_closed():
    state = {
        "paper_positions": {
            "a": {"status": "open", "position_id": "a"},
            "b": {"status": "closed", "position_id": "b"},
        }
    }
    assert len(open_paper_positions(state)) == 1


def test_already_entered_today():
    state = {
        "entry_log": [
            {
                "entered": True,
                "evaluated_at": "2026-06-16T19:45:00+00:00",
                "position_id": "paper:XSP:2026-07-18:6010",
            },
        ]
    }
    assert already_entered_today(state, date(2026, 6, 16)) is True
    assert already_entered_today(state, date(2026, 6, 17)) is False


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
        "xsp_killer.lane_a_entry.evaluate_ta_signals", lambda rules, now_et=None: fake
    )


def test_run_paper_entry_outside_window(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_PAPER_ENTRY", "true")
    _mock_ta_entry_ok(monkeypatch)
    decision = run_paper_entry(
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "paper.jsonl",
        now_et=datetime(2026, 6, 16, 10, 0, tzinfo=ET),
        publish_intel=False,
    )
    assert decision.entered is False
    assert decision.skip_reason is not None


def test_run_paper_entry_success_mocked(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_PAPER_ENTRY", "true")
    _mock_ta_entry_ok(monkeypatch)
    rules_path = tmp_path / "rules-close-window.yaml"
    rules_path.write_text(
        "ta:\n  entry:\n    mode: close_window_only\n",
        encoding="utf-8",
    )

    def _regime():
        return "GREEN", True, None, None

    monkeypatch.setattr("xsp_killer.lane_a_entry.read_regime_detail", _regime)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.fetch_spy_ohlcv",
        lambda: (600.0, 595.0, 0.5, "2026-06-17"),
    )
    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spx_proxy", lambda: 6010.0)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_expiration",
        lambda rules, today=None, dte_pick="min", dte_target=None: date(2026, 7, 18),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_strike",
        lambda *args, **kwargs: (
            6010.0,
            2.45,
            0.52,
        ),
    )

    decision = run_paper_entry(
        rules_path=rules_path,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "paper.jsonl",
        now_et=datetime(2026, 6, 16, 15, 47, tzinfo=ET),
        publish_intel=False,
    )
    assert decision.entered is True
    assert decision.position is not None
    assert decision.position["strike"] == 6010.0
    assert decision.position["average_price"] > 2.45
    assert decision.position["entry_reason"] == "close_window_long_call"
    assert decision.position["spx_at_entry"] == 6010.0


def test_run_paper_entry_blocks_when_open_position(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_PAPER_ENTRY", "true")
    _mock_ta_entry_ok(monkeypatch)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"paper_positions":{"p1":{"status":"open","position_id":"p1"}}}\n',
        encoding="utf-8",
    )
    decision = run_paper_entry(
        state_path=state_path,
        log_path=tmp_path / "paper.jsonl",
        now_et=datetime(2026, 6, 16, 15, 47, tzinfo=ET),
        force=True,
        publish_intel=False,
    )
    assert decision.entered is False
    assert "max open" in (decision.skip_reason or "").lower()


def test_already_entered_skips_failed_attempt():
    state = {
        "entry_log": [
            {
                "entered": False,
                "evaluated_at": "2026-06-16T19:45:00+00:00",
                "skip_reason": "regime",
            },
            {"entered": True, "evaluated_at": "2026-06-16T19:45:00+00:00"},
        ]
    }
    assert already_entered_today(state, date(2026, 6, 16)) is False


def test_spy_to_xsp_premium_scale_in_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_PAPER_ENTRY", "true")
    _mock_ta_entry_ok(monkeypatch)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.read_regime_detail",
        lambda: ("GREEN", True, None, None),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.fetch_spy_ohlcv",
        lambda: (600.0, 595.0, 0.5, "2026-06-17"),
    )
    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spx_proxy", lambda: 6010.0)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_expiration",
        lambda rules, today=None, dte_pick="min", dte_target=None: date(2026, 7, 18),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_strike",
        lambda *args, **kwargs: (
            6010.0,
            24.5,
            0.52,
        ),
    )
    decision = run_paper_entry(
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "paper.jsonl",
        now_et=datetime(2026, 6, 16, 15, 47, tzinfo=ET),
        publish_intel=False,
    )
    assert decision.entered is True
    pos = decision.position
    assert pos["entry_mid_premium"] == 24.5
    assert pos["average_price"] > pos["entry_mid_premium"]


def test_run_paper_entry_bb_bounce_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_PAPER_ENTRY", "true")
    rules_path = tmp_path / "rules-bb.yaml"
    rules_path.write_text("ta:\n  entry:\n    mode: bb_bounce\n", encoding="utf-8")
    ta_signal = TaSignal(
        signal="bb_bounce_entry",
        primary=None,
        confirm=None,
        entry_ok=True,
        exit_ok=False,
        upper_bb_touched=False,
        detail="bb bounce confirmed",
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.read_regime_detail",
        lambda: ("GREEN", True, None, None),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.fetch_spy_ohlcv",
        lambda: (600.0, 595.0, 0.5, "2026-06-17"),
    )
    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spx_proxy", lambda: 6010.0)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_expiration",
        lambda rules, today=None, dte_pick="min", dte_target=None: date(2026, 7, 18),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.pick_strike",
        lambda *args, **kwargs: (
            6010.0,
            2.45,
            0.52,
        ),
    )

    decision = run_paper_entry(
        rules_path=rules_path,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "paper.jsonl",
        now_et=datetime(2026, 6, 16, 10, 0, tzinfo=ET),
        publish_intel=False,
        ta_signal=ta_signal,
    )
    assert decision.entered is True
    assert decision.position is not None
    assert decision.position["entry_reason"] == "bb_bounce_long_call"


def test_bucket_skip_reason_regime():
    assert _bucket_skip_reason("regime YELLOW blocks new risk") == "regime_gate"


def test_bucket_skip_reason_conductor_shadow():
    assert (
        _bucket_skip_reason("conductor_shadow: macro regime RED") == "conductor_shadow"
    )


def test_bucket_skip_reason_consecutive_losses_risk_gate():
    assert _bucket_skip_reason("consecutive paper losses halt (3 >= 3)") == "risk_gate"


def test_entry_telemetry_counts_skips_and_regime(tmp_path):
    state: dict = {"entry_log": []}
    decision = EntryDecision(
        entered=False,
        evaluated_at="2026-06-26T19:45:00+00:00",
        logic_version="test",
        in_window=True,
        regime="YELLOW",
        regime_ok=False,
        prior_day_spy_return_pct=None,
        prior_day_ok=True,
        skip_reason="regime YELLOW blocks new risk",
    )
    _finalize_entry(
        state,
        tmp_path / "state.json",
        decision,
        publish_intel=False,
        brief_path=False,
        log_path=tmp_path / "paper.jsonl",
    )
    tel = state["entry_telemetry"]
    assert tel["regime_counts"]["YELLOW"] == 1
    assert tel["skip_reason_counts"]["regime_gate"] == 1
    assert tel["sessions_evaluated"] == 1
    assert tel["entered_sessions"] == 0


def test_entry_telemetry_respects_pnl_epoch(tmp_path):
    epoch = "2026-06-23T22:20:36+00:00"
    state = {
        "pnl_epoch_at": epoch,
        "entry_log": [
            {
                "evaluated_at": "2026-06-22T19:45:00+00:00",
                "entered": True,
                "regime": "GREEN",
                "skip_reason": None,
            },
            {
                "evaluated_at": "2026-06-26T19:45:00+00:00",
                "entered": False,
                "regime": "YELLOW",
                "skip_reason": "regime YELLOW blocks new risk",
            },
        ],
    }
    logs = entry_logs_for_epoch(state)
    assert len(logs) == 1
    tel = summarize_entry_telemetry_from_logs(logs)
    assert tel["entered_sessions"] == 0
    assert tel["sessions_evaluated"] == 1
    assert tel["skip_reason_counts"] == {"regime_gate": 1}
    assert tel["regime_counts"] == {"YELLOW": 1}

    brief_path = tmp_path / "telemetry.json"
    _write_entry_telemetry_brief(state, out_path=brief_path)
    import json

    payload = json.loads(brief_path.read_text(encoding="utf-8"))
    assert payload["pnl_epoch_at"] == epoch
    assert payload["evals_total"] == 1
    assert payload["entered_sessions"] == 0
    assert payload["sessions_evaluated"] == 1
    assert "entered" not in payload["skip_reason_counts"]


def test_et_session_date_uses_new_york_calendar():
    assert et_session_date("2026-06-27T01:15:00+00:00") == "2026-06-26"


def test_unique_et_sessions_dedupes_intraday_and_excludes_weekends():
    logs = [
        {"evaluated_at": "2026-06-26T19:45:00+00:00"},
        {"evaluated_at": "2026-06-26T20:00:00+00:00"},
        {"evaluated_at": "2026-06-27T19:45:00+00:00"},
        {"evaluated_at": "2026-06-29T19:45:00+00:00"},
        {"evaluated_at": "2026-07-03T19:45:00+00:00"},
    ]
    assert unique_et_sessions(logs) == ["2026-06-26", "2026-06-29"]


def test_is_et_trading_session_excludes_2026_nyse_holidays():
    assert is_et_trading_session(date(2026, 7, 2)) is True
    assert is_et_trading_session(date(2026, 7, 3)) is False
    assert is_et_trading_session(date(2026, 7, 4)) is False


def test_scoreboard_entry_stale_false_over_holiday_weekend():
    last_eval = datetime(2026, 7, 3, 23, 55, tzinfo=timezone.utc)
    now = datetime(2026, 7, 5, 17, 44, tzinfo=timezone.utc)
    assert scoreboard_entry_stale(last_eval, now=now) is False


def test_scoreboard_entry_stale_true_after_missed_trading_session():
    last_eval = datetime(2026, 7, 2, 23, 55, tzinfo=timezone.utc)
    now = datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc)
    assert scoreboard_entry_stale(last_eval, now=now) is True


def test_entry_telemetry_dedupes_sessions_and_keeps_raw_eval_total():
    logs = [
        {
            "evaluated_at": "2026-06-26T19:45:00+00:00",
            "entered": False,
            "skip_reason": "regime YELLOW blocks new risk",
            "regime": "YELLOW",
        },
        {
            "evaluated_at": "2026-06-26T20:00:00+00:00",
            "entered": False,
            "skip_reason": "regime YELLOW blocks new risk",
            "regime": "YELLOW",
        },
        {
            "evaluated_at": "2026-06-29T19:45:00+00:00",
            "entered": True,
            "regime": "GREEN",
        },
        {
            "evaluated_at": "2026-06-28T19:45:00+00:00",
            "entered": False,
            "skip_reason": "regime RED blocks new risk",
            "regime": "RED",
        },
    ]
    tel = summarize_entry_telemetry_from_logs(logs)
    assert tel["evals_total"] == 4
    assert tel["sessions_evaluated"] == 2
    assert tel["entered_sessions"] == 1
    assert tel["skip_reason_counts"]["entered"] == 1
    assert tel["skip_reason_counts"]["regime_gate"] == 1


def test_reap_expired_paper_positions_closes_only_expired(tmp_path):
    state = {
        "paper_positions": {
            "expired": {
                "position_id": "expired",
                "status": "open",
                "expiration_date": "2026-06-13",
                "logic_version": "xsp_lane_a_v2",
            },
            "active": {
                "position_id": "active",
                "status": "open",
                "expiration_date": "2026-06-30",
                "logic_version": "xsp_lane_a_v2",
            },
        }
    }
    closed = reap_expired_paper_positions(
        state,
        state_path=tmp_path / "state.json",
        evaluated_at="2026-06-16T14:00:00+00:00",
        today=date(2026, 6, 16),
    )
    assert len(closed) == 1
    assert state["paper_positions"]["expired"]["status"] == "closed"
    assert state["paper_positions"]["expired"]["exit_reason"] == "expired"
    assert state["paper_positions"]["active"]["status"] == "open"
    assert state["paper_events"][-1]["position_id"] == "expired"


def test_reap_expired_books_full_debit_loss(tmp_path):
    from xsp_killer.paper_economics import PaperEconomics, pnl_from_entry_fill

    state = {
        "paper_positions": {
            "paper:XSP:2026-06-13:6000": {
                "position_id": "paper:XSP:2026-06-13:6000",
                "status": "open",
                "expiration_date": "2026-06-13",
                "quantity": 2.0,
                "average_price": 2.5,
                "entry_mid_premium": 2.4,
                "logic_version": "xsp_lane_a_v2",
            }
        }
    }
    closed = reap_expired_paper_positions(
        state,
        state_path=tmp_path / "state.json",
        evaluated_at="2026-06-16T14:00:00+00:00",
        today=date(2026, 6, 16),
    )
    assert len(closed) == 1
    econ = PaperEconomics.from_yaml()
    expected_per = pnl_from_entry_fill(entry_fill=2.5, exit_mid=0.0, econ=econ)
    row = state["paper_positions"]["paper:XSP:2026-06-13:6000"]
    assert row["status"] == "closed"
    assert row["exit_reason"] == "expired"
    assert row["exit_pnl_per_contract"] == expected_per
    assert row["exit_pnl_usd"] == round(expected_per * 2.0, 2)
    assert expected_per < 0
    evt = state["paper_events"][-1]
    assert evt["exit_reason"] == "expired"
    assert evt["paper_pnl_per_contract"] == expected_per
    assert evt["paper_pnl_usd"] == round(expected_per * 2.0, 2)


# --- Live entry buy path (gated) --------------------------------------------

import types  # noqa: E402

from xsp_killer.lane_a_entry import (  # noqa: E402
    _live_entry_ref_id,
    _maybe_place_live_entry,
)


def _mk_decision() -> EntryDecision:
    return EntryDecision(
        entered=True,
        evaluated_at="2026-07-07T20:00:00+00:00",
        logic_version="xsp_lane_a_v1",
        in_window=True,
        regime="green",
        regime_ok=True,
        prior_day_spy_return_pct=0.5,
        prior_day_ok=True,
    )


_LANE = types.SimpleNamespace(
    dte_min=14,
    dte_max=60,
    stop_loss_pct=0.20,
    logic_version="xsp_lane_a_v2",
)
_ENTRY = types.SimpleNamespace(
    chain_symbol="XSP",
    dte_pick="min",
    dte_target=None,
    strike_max_steps_from_atm=1,
    strike_pick="cheapest_near_atm",
    quantity=1,
)


def _human_promote(monkeypatch, tmp_path, variant_id: str = "xsp_lane_a_v2") -> None:
    """Satisfy dual-env + ack-file human review gate for live places."""
    from xsp_killer.live_gates import REQUIRED_STATEMENT

    ack = tmp_path / "LIVE_HUMAN_REVIEW.json"
    ack.write_text(
        __import__("json").dumps(
            {"variant_id": variant_id, "statement": REQUIRED_STATEMENT}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", variant_id)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK", variant_id)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(ack))


class _FakeEntryAdapter:
    def __init__(self, *, ask=1.0, buying_power=1000.0):
        self._ask = ask
        self._bp = buying_power
        self.placed = None

    def select_entry_contract(self, **kw):
        return {
            "instrument_id": "inst-xyz",
            "strike": 755.0,
            "expiration_date": "2026-07-21",
            "dte": 14,
            "bid": self._ask - 0.1,
            "ask": self._ask,
            "mark": self._ask,
        }

    def get_buying_power(self, account_number=None):
        return self._bp

    def buy_to_open(self, *, instrument_id, limit_price, quantity, ref_id=None):
        self.placed = {
            "instrument_id": instrument_id,
            "limit_price": limit_price,
            "quantity": quantity,
            "ref_id": ref_id,
        }
        return {"review": {"ok": 1}, "placed": {"id": "order-1"}}


def _patch_mcp(monkeypatch, *, enabled, entries, kill, adapter):
    import xsp_killer.robinhood_mcp as rhm

    monkeypatch.setattr(rhm, "rh_mcp_enabled", lambda: enabled)
    monkeypatch.setattr(rhm, "live_entries_enabled", lambda **k: entries)
    monkeypatch.setattr(rhm, "kill_switch_engaged", lambda: kill)
    monkeypatch.setattr(rhm, "RobinhoodMCPAdapter", lambda *a, **k: adapter)


def _patch_green_regime(monkeypatch):
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.read_regime_detail",
        lambda: ("GREEN", True, None, None),
    )


def test_live_entry_ref_id_is_deterministic():
    a = _live_entry_ref_id("inst-xyz", "2026-07-07")
    b = _live_entry_ref_id("inst-xyz", "2026-07-07")
    c = _live_entry_ref_id("inst-xyz", "2026-07-08")
    assert a == b
    assert a != c


def test_live_entry_noop_when_mcp_off(monkeypatch):
    d = _mk_decision()
    _patch_mcp(monkeypatch, enabled=False, entries=True, kill=False, adapter=None)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order is None


def test_live_entry_skips_when_entries_disabled(monkeypatch):
    d = _mk_decision()
    _patch_mcp(monkeypatch, enabled=True, entries=False, kill=False, adapter=None)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "disabled" in d.live_order["reason"]


def test_live_entry_blocked_by_kill_switch(monkeypatch):
    d = _mk_decision()
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=True, adapter=None)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "kill switch" in d.live_order["reason"]


def test_live_entry_skips_when_variant_allowlist_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("XSP_LANE_A_LIVE_VARIANT_ID", raising=False)
    monkeypatch.delenv("XSP_LANE_A_LIVE_HUMAN_ACK", raising=False)
    monkeypatch.setenv(
        "XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(tmp_path / "missing.json")
    )
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=1.0, buying_power=1000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "LIVE_VARIANT_ID unset" in d.live_order["reason"]
    assert adapter.placed is None


def test_live_entry_skips_when_variant_allowlist_differs(monkeypatch, tmp_path):
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", "different_variant")
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK", "different_variant")
    monkeypatch.setenv(
        "XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(tmp_path / "missing.json")
    )
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=1.0, buying_power=1000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "human review blocked" in d.live_order["reason"]
    assert adapter.placed is None


def test_live_entry_skips_red_regime(monkeypatch, tmp_path):
    _human_promote(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.read_regime_detail",
        lambda: ("RED", False, None, None),
    )
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=1.0, buying_power=1000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order == {
        "placed": False,
        "reason": "live skipped: RED regime (shadow only)",
    }
    assert adapter.placed is None


def test_live_entry_fails_safe_on_insufficient_buying_power(monkeypatch, tmp_path):
    _human_promote(monkeypatch, tmp_path)
    _patch_green_regime(monkeypatch)
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=2.0, buying_power=50.0)  # cost 200 > 50
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "insufficient buying power" in d.live_order["reason"]
    assert adapter.placed is None


def test_live_entry_skips_when_est_max_loss_exceeds_cap(monkeypatch, tmp_path):
    _human_promote(monkeypatch, tmp_path)
    _patch_green_regime(monkeypatch)
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=1000.0, buying_power=1_000_000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "planned stop loss" in d.live_order["reason"]
    assert d.live_order["est_max_loss"] == 20000.0
    assert adapter.placed is None


def test_live_entry_skips_when_debit_exceeds_cap(monkeypatch, tmp_path):
    # cost 3000 (ask 30 x 100) > max_debit_usd 2500, while the modeled stop-loss
    # estimate (3000 x 20% = 600) is well under max_loss_usd and cost is under
    # max_cost_frac of buying power -> only the full-debit gate should trip.
    _human_promote(monkeypatch, tmp_path)
    _patch_green_regime(monkeypatch)
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=30.0, buying_power=1_000_000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "max debit" in d.live_order["reason"]
    assert d.live_order["max_debit_usd"] == 2500.0
    assert d.live_order["cost_estimate"] == 3000.0
    assert adapter.placed is None


def test_live_variant_allowed_requires_exact_match():
    from xsp_killer.lane_a_entry import _live_variant_allowed

    assert _live_variant_allowed("xsp_lane_a_v2", "xsp_lane_a_v2") is True
    # Suffix matches must NOT authorize live (previously allowed via endswith).
    assert _live_variant_allowed("evil_xsp_lane_a_v2", "xsp_lane_a_v2") is False
    assert _live_variant_allowed("xsp_lane_a_v2", "lane_a_v2") is False
    assert _live_variant_allowed("xsp_lane_a_v2", "") is False
    assert _live_variant_allowed("", "xsp_lane_a_v2") is False
    assert _live_variant_allowed("xsp_lane_a_v2", None) is False


def test_live_entry_skips_when_variant_is_suffix_only(monkeypatch, tmp_path):
    # A current variant that merely ends with the allowlisted id must be refused.
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", "lane_a_v2")
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK", "lane_a_v2")
    monkeypatch.setenv(
        "XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(tmp_path / "missing.json")
    )
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=1.0, buying_power=1000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "human review blocked" in d.live_order["reason"]
    assert adapter.placed is None


def test_live_entry_places_when_authorized_and_funded(monkeypatch, tmp_path):
    _human_promote(monkeypatch, tmp_path)
    _patch_green_regime(monkeypatch)
    d = _mk_decision()
    adapter = _FakeEntryAdapter(ask=1.0, buying_power=1000.0)  # cost 100 <= 1000
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is True
    assert adapter.placed["instrument_id"] == "inst-xyz"
    assert adapter.placed["ref_id"] == _live_entry_ref_id("inst-xyz", "2026-07-07")
    assert d.live_order["reviewer"]["decision"] == "approve"


class _WideSpreadAdapter(_FakeEntryAdapter):
    def select_entry_contract(self, **kw):
        c = super().select_entry_contract(**kw)
        c["bid"] = 0.5  # ask 1.0 vs bid 0.5 -> ~67% spread
        return c


def test_live_entry_vetoed_by_reviewer_on_wide_spread(monkeypatch, tmp_path):
    _human_promote(monkeypatch, tmp_path)
    monkeypatch.delenv("XSP_LANE_A_LIVE_REVIEWER", raising=False)
    _patch_green_regime(monkeypatch)
    d = _mk_decision()
    adapter = _WideSpreadAdapter(ask=1.0, buying_power=1000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    assert d.live_order["placed"] is False
    assert "spread" in d.live_order["reason"]
    assert d.live_order["reviewer"]["decision"] == "veto"
    assert adapter.placed is None


def test_live_entry_reviewer_can_be_disabled(monkeypatch, tmp_path):
    _human_promote(monkeypatch, tmp_path)
    monkeypatch.setenv("XSP_LANE_A_LIVE_REVIEWER", "false")
    _patch_green_regime(monkeypatch)
    d = _mk_decision()
    adapter = _WideSpreadAdapter(ask=1.0, buying_power=1000.0)
    _patch_mcp(monkeypatch, enabled=True, entries=True, kill=False, adapter=adapter)
    _maybe_place_live_entry(
        d, lane_rules=_LANE, entry_rules=_ENTRY, today=date(2026, 7, 7)
    )
    # Reviewer off -> the wide-spread order is no longer vetoed by it.
    assert d.live_order["placed"] is True
    assert d.live_order["reviewer"] is None
