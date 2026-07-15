"""Unit tests for XSP Lane A Phase 0 monitor (no live Robinhood)."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import xsp_killer.lane_a_monitor as lane_a_monitor
from xsp_killer.lane_a_monitor import (
    ExitAlert,
    LaneAPosition,
    LaneRules,
    _exit_ref_id,
    _real_option_id,
    classify_position,
    close_paper_positions_on_exit,
    compute_dte,
    dry_run_exit_reviews_via_mcp,
    evaluate_exit_alerts,
    xsp_session_open,
    is_lane_a_contract,
    load_state,
    record_paper_exit_signals,
    rh_poll_enabled,
    run_monitor,
    save_state,
)
from xsp_killer.lane_a_ta import TaSignal

ET = ZoneInfo("America/New_York")
FIXED_TODAY = date(2026, 6, 20)

RULES = LaneRules(
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


def _raw(
    *,
    chain: str = "XSP",
    opt_type: str = "call",
    exp: str = "2026-07-18",
    strike: float = 6000.0,
    qty: float = 1.0,
    avg: float = 2.50,
    mark: float | None = 2.00,
) -> dict:
    return {
        "id": f"{chain}-{exp}-{strike}",
        "chain_symbol": chain,
        "type": opt_type,
        "expiration_date": exp,
        "strike_price": strike,
        "quantity": qty,
        "average_price": avg,
        "mark_price": mark,
    }


def test_lane_a_classify_call_dte_in_range():
    pos = classify_position(_raw(), RULES, today=FIXED_TODAY)
    assert pos is not None
    assert pos.chain_symbol == "XSP"
    assert 14 <= pos.dte <= 60


def test_lane_a_rejects_put():
    assert classify_position(_raw(opt_type="put"), RULES, today=FIXED_TODAY) is None


def test_lane_a_rejects_january_expiry():
    assert classify_position(_raw(exp="2027-01-15"), RULES, today=FIXED_TODAY) is None


def test_lane_a_rejects_short_dte():
    assert classify_position(_raw(exp="2026-06-20"), RULES, today=FIXED_TODAY) is None


def test_lane_a_rejects_non_spx_chain():
    assert classify_position(_raw(chain="AAPL"), RULES, today=FIXED_TODAY) is None


def test_stop_loss_20pct_alert():
    pos = classify_position(_raw(avg=2.00, mark=1.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    now = datetime(2026, 6, 16, 9, 45, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert any(a.exit_reason == "stop_loss" for a in alerts)


def test_classify_position_preserves_zero_mark():
    pos = classify_position(_raw(avg=2.00, mark=0.0), RULES, today=FIXED_TODAY)
    assert pos is not None
    assert pos.mark_price == 0.0


def test_zero_mark_triggers_stop_loss_not_suppression():
    pos = classify_position(_raw(avg=2.00, mark=0.0), RULES, today=FIXED_TODAY)
    assert pos is not None
    assert pos.mark_price == 0.0
    now = datetime(2026, 6, 16, 9, 45, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert any(a.exit_reason == "stop_loss" for a in alerts)
    # Return pct must be computable from a preserved zero mark (full loss).
    assert pos.pnl_per_contract is not None
    assert pos.pnl_per_contract < 0


def test_run_monitor_evaluates_paper_book_when_rh_positions_present(
    tmp_path, monkeypatch
):
    """Paper exits must still evaluate when a real RH UUID is also classified."""
    paper_id = "paper:XSP:2026-07-18:6000"
    rh_id = "11111111-1111-1111-1111-111111111111"
    state = {
        "paper_positions": {
            paper_id: {
                "position_id": paper_id,
                "lane": "A",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 6000.0,
                "expiration_date": "2026-07-18",
                "quantity": 1.0,
                "average_price": 2.5,
                "mark_price": 2.5,
                "entry_mid_premium": 2.5,
                "status": "open",
                "entry_ts": "2026-06-15T19:45:00+00:00",
            }
        }
    }
    save_state(tmp_path / "state.json", state)

    monkeypatch.setattr(lane_a_monitor, "rh_read_enabled", lambda: True)
    monkeypatch.setattr(
        lane_a_monitor,
        "fetch_robinhood_option_positions",
        lambda: (
            [
                {
                    "id": rh_id,
                    "chain_symbol": "XSP",
                    "type": "call",
                    "expiration_date": "2026-07-18",
                    "strike_price": 6010.0,
                    "quantity": 1.0,
                    "average_price": 3.0,
                    "mark_price": 3.0,
                }
            ],
            None,
        ),
    )

    def _stop_loss_mark(rows):
        return [{**row, "mark_price": 1.5} for row in rows]

    monkeypatch.setattr(lane_a_monitor, "refresh_paper_marks", _stop_loss_mark)
    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spx_proxy", lambda: 6000.0)

    report = run_monitor(
        state_path=tmp_path / "state.json",
        now_et=datetime(2026, 6, 16, 9, 45, tzinfo=ET),
        publish_intel=False,
        fetch_ta=False,
        write_paper_brief=False,
    )

    pos_ids = {p["position_id"] for p in report.positions}
    assert rh_id in pos_ids
    assert paper_id in pos_ids
    assert any(
        a["position_id"] == paper_id and a["exit_reason"] == "stop_loss"
        for a in report.alerts
    )
    refreshed = load_state(tmp_path / "state.json")
    assert refreshed["paper_positions"][paper_id]["status"] == "closed"
    assert refreshed["paper_positions"][paper_id]["exit_reason"] == "stop_loss"


def test_no_exit_when_xsp_session_closed():
    pos = classify_position(_raw(avg=2.00, mark=1.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    # Weekday after curb / before GTH (18:00 ET)
    now = datetime(2026, 6, 16, 18, 0, tzinfo=ET)
    assert not xsp_session_open(now)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert alerts == []


def test_gth_allows_stop_loss():
    pos = classify_position(_raw(avg=2.00, mark=1.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    now = datetime(2026, 6, 16, 8, 30, tzinfo=ET)
    assert xsp_session_open(now)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert any(a.exit_reason == "stop_loss" for a in alerts)


def test_gth_allows_take_profit():
    pos = classify_position(_raw(avg=2.00, mark=2.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    ta = TaSignal("upper_bb_exit", None, None, False, True, True, "upper touch")
    now = datetime(2026, 6, 16, 8, 45, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now, ta_signal=ta)
    assert any(a.exit_reason in ("take_profit", "upper_bb_rejection") for a in alerts)


def test_curb_allows_take_profit():
    pos = classify_position(_raw(avg=2.00, mark=2.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    ta = TaSignal("upper_bb_exit", None, None, False, True, True, "upper touch")
    now = datetime(2026, 6, 16, 16, 30, tzinfo=ET)
    assert xsp_session_open(now)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now, ta_signal=ta)
    assert any(a.exit_reason in ("take_profit", "upper_bb_rejection") for a in alerts)


def test_rth_afternoon_allows_take_profit_without_sell_window():
    """Conditions-only: TP fires mid-RTH, not gated to a morning clock window."""
    pos = classify_position(_raw(avg=2.00, mark=2.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    ta = TaSignal("upper_bb_exit", None, None, False, True, True, "upper touch")
    now = datetime(2026, 6, 16, 13, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now, ta_signal=ta)
    assert any(a.exit_reason in ("take_profit", "upper_bb_rejection") for a in alerts)


def test_take_profit_waits_without_upper_bb():
    pos = classify_position(_raw(avg=2.00, mark=2.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    ta = TaSignal("none", None, None, False, False, False, "")
    now = datetime(2026, 6, 16, 9, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now, ta_signal=ta)
    assert alerts == []


def test_take_profit_fires_with_upper_bb_touch():
    pos = classify_position(_raw(avg=2.00, mark=2.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    ta = TaSignal("upper_bb_exit", None, None, False, True, True, "upper touch")
    now = datetime(2026, 6, 16, 9, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now, ta_signal=ta)
    assert any(a.exit_reason in ("take_profit", "upper_bb_rejection") for a in alerts)


def test_no_clock_forced_time_stop():
    pos = classify_position(_raw(avg=2.00, mark=2.10), RULES, today=FIXED_TODAY)
    assert pos is not None
    pos.entry_ts = "2026-06-15T19:45:00+00:00"
    now = datetime(2026, 6, 16, 9, 30, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert not any(a.exit_reason == "time_stop" for a in alerts)


def test_time_stop_skips_same_entry_day():
    pos = classify_position(_raw(avg=2.00, mark=2.10), RULES, today=FIXED_TODAY)
    assert pos is not None
    pos.entry_ts = "2026-06-14T19:45:00+00:00"
    now = datetime(2026, 6, 16, 15, 45, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert not any(a.exit_reason == "time_stop" for a in alerts)


def test_stop_loss_outside_tp_window():
    pos = classify_position(_raw(avg=2.00, mark=1.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    now = datetime(2026, 6, 16, 10, 30, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert any(a.exit_reason == "stop_loss" for a in alerts)


def test_rh_poll_skipped_by_default(monkeypatch):
    monkeypatch.delenv("XSP_LANE_A_RH_POLL", raising=False)
    assert rh_poll_enabled() is False


def test_run_monitor_with_fixture(tmp_path):
    fixture = [_raw()]
    report = run_monitor(
        state_path=tmp_path / "state.json",
        positions_override=fixture,
        now_et=datetime(2026, 6, 16, 9, 45, tzinfo=ET),
        publish_intel=False,
    )
    assert report.phase == 0
    assert report.logic_version == "xsp_lane_a_v2"
    assert len(report.positions) == 1
    assert report.rh_connected is True
    assert report.paper_mtm_usd is not None


def test_paper_exit_dedup(tmp_path):
    state = load_state(tmp_path / "state.json")
    alerts = [ExitAlert("p1", "stop_loss", "red", -50.0, -50.0)]
    new1 = record_paper_exit_signals(
        state,
        alerts,
        evaluated_at="2026-06-14T14:00:00+00:00",
        logic_version="xsp_lane_a_v2",
    )
    new2 = record_paper_exit_signals(
        state,
        alerts,
        evaluated_at="2026-06-14T14:30:00+00:00",
        logic_version="xsp_lane_a_v2",
    )
    assert len(new1) == 1
    assert len(new2) == 0
    save_state(tmp_path / "state.json", state)


def test_upper_bb_exit_in_sell_window():
    pos = classify_position(_raw(avg=2.00, mark=2.50), RULES, today=FIXED_TODAY)
    assert pos is not None
    ta = TaSignal(
        signal="upper_bb_exit",
        primary=None,
        confirm=None,
        entry_ok=False,
        exit_ok=True,
        upper_bb_touched=True,
        detail="upper BB rejection",
    )
    alerts = evaluate_exit_alerts(
        pos, RULES, now_et=datetime(2026, 6, 16, 9, 0, tzinfo=ET), ta_signal=ta
    )
    assert any(a.exit_reason == "upper_bb_rejection" for a in alerts)


def test_compute_dte():
    exp = date(2026, 7, 1)
    assert compute_dte(exp, today=date(2026, 6, 14)) == 17


def test_is_lane_a_contract_boundary():
    exp = date(2026, 7, 28)
    assert is_lane_a_contract(
        chain_symbol="SPX",
        option_type="call",
        expiration=exp,
        rules=RULES,
        today=date(2026, 6, 14),
    )


def test_read_regime_from_intel_dict(monkeypatch):
    from xsp_killer import intel

    monkeypatch.setattr(intel.IntelReader, "read", lambda key: {"regime": "GREEN"})
    from xsp_killer.lane_a_monitor import read_regime

    regime, ok = read_regime()
    assert regime == "GREEN"
    assert ok is True


def test_pnl_uses_entry_fill_not_double_count():
    from xsp_killer.paper_economics import (
        PaperEconomics,
        entry_fill_premium,
        pnl_from_entry_fill,
    )

    econ = PaperEconomics(
        commission_usd_per_contract=0.65,
        slippage_pct_of_premium=0.005,
        slippage_usd_per_share=0.12,
        slippage_max_pct_of_premium=0.015,
    )
    entry_mid = 24.5
    entry_fill = entry_fill_premium(entry_mid, econ)
    pnl = pnl_from_entry_fill(entry_fill=entry_fill, exit_mid=29.4, econ=econ)
    assert pnl < (29.4 - 24.5) * 100.0
    assert pnl > 0


def test_open_paper_position_monitored_below_entry_dte_min(tmp_path):
    """Hold entered at dte_min must still get exit monitoring when DTE drops."""
    from xsp_killer.lane_a_monitor import paper_positions_to_lane

    state = {
        "paper_positions": {
            "paper:XSP:2026-06-30:7520": {
                "position_id": "paper:XSP:2026-06-30:7520",
                "lane": "A",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 7520.0,
                "expiration_date": "2026-06-30",
                "quantity": 1.0,
                "average_price": 66.39,
                "mark_price": 61.8,
                "entry_mid_premium": 65.4,
                "status": "open",
            }
        }
    }
    today = __import__("datetime").date(2026, 6, 17)
    rows = [state["paper_positions"]["paper:XSP:2026-06-30:7520"]]
    classified = paper_positions_to_lane(rows, RULES, today=today)
    assert len(classified) == 1
    assert classified[0].dte == 13


def test_stale_mark_suppresses_take_profit_not_risk_exits():
    from xsp_killer.lane_a_monitor import LaneAPosition, evaluate_exit_alerts

    # A stale/suspect mark must NOT bank a take-profit, but risk exits are not
    # blocked by staleness (see the swing-hold stale-mark SL test below).
    pos = LaneAPosition(
        position_id="paper:XSP:2026-07-17:7505",
        chain_symbol="XSP",
        option_type="call",
        strike=7505.0,
        expiration_date=date(2026, 7, 17),
        quantity=1.0,
        average_price=6.0,
        mark_price=7.5,
        dte=28,
        entry_ts="2026-06-17T13:40:00+00:00",  # same ET day as `now` -> no time_stop
        entry_mid_premium=6.0,
        mark_quote_stale=True,
    )
    pos.pnl_per_contract = 150.0
    pos.pnl_usd = 150.0
    now = datetime(2026, 6, 17, 9, 0, tzinfo=ET)
    # ret = +25% >= TP 20%, in the sell window, but the stale mark suppresses TP.
    assert evaluate_exit_alerts(pos, RULES, now_et=now) == []
    # A fresh mark on the identical setup DOES take profit.
    pos.mark_quote_stale = False
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now)
    assert [a.exit_reason for a in alerts] == ["take_profit"]


def test_suppress_morning_cut_for_long_dte():
    from xsp_killer.lane_a_monitor import LaneAPosition, evaluate_exit_alerts

    pos = LaneAPosition(
        position_id="paper:XSP:2026-07-31:7500",
        chain_symbol="XSP",
        option_type="call",
        strike=7500.0,
        expiration_date=date(2026, 7, 31),
        quantity=1.0,
        average_price=6.0,
        mark_price=5.9,
        dte=35,
        entry_ts="2026-06-16T19:45:00+00:00",
        entry_mid_premium=5.8,
    )
    pos.pnl_per_contract = -10.0
    pos.pnl_usd = -10.0
    now = datetime(2026, 6, 17, 10, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, RULES, now_et=now, suppress_morning_cut_dte=30)
    assert alerts == []


def test_write_paper_pnl_brief_includes_dual_notional(tmp_path, monkeypatch):
    from xsp_killer.lane_a_monitor import MonitorReport, write_paper_pnl_brief

    monkeypatch.setenv("XSP_SPY_TO_XSP_PREMIUM_SCALE", "10")
    report = MonitorReport(
        evaluated_at="2026-06-30T19:45:23+00:00",
        phase=0,
        logic_version="xsp_lane_a_v2",
        regime="GREEN",
        regime_allows_new_risk=True,
        paper_mtm_usd=-89.95,
    )
    out = write_paper_pnl_brief({}, report=report, out_path=tmp_path / "pnl.json")
    payload = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert payload["premium_scale_used"] == 10.0
    assert payload["open_positions_mtm_usd"] == -89.95
    assert payload["open_positions_mtm_usd_1x"] == -9.0


def test_write_paper_pnl_brief_falls_back_to_rules_logic_version(tmp_path):
    from xsp_killer.lane_a_monitor import write_paper_pnl_brief

    out = write_paper_pnl_brief({}, report=None, out_path=tmp_path / "pnl.json")
    payload = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert payload["logic_version"] == "xsp_lane_a_v2"


def test_write_paper_pnl_brief_computes_open_mtm_without_report(tmp_path, monkeypatch):
    from xsp_killer.lane_a_monitor import (
        compute_paper_open_mtm,
        write_paper_pnl_brief,
    )

    monkeypatch.setenv("XSP_SPY_TO_XSP_PREMIUM_SCALE", "10")
    state = {
        "paper_positions": {
            "paper:XSP:2026-07-17:7500": {
                "position_id": "paper:XSP:2026-07-17:7500",
                "status": "open",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 7500.0,
                "expiration_date": "2026-07-17",
                "quantity": 1,
                "average_price": 6.5,
                "mark_price": 6.0,
            }
        }
    }
    expected_scaled, expected_1x = compute_paper_open_mtm(state)
    out = write_paper_pnl_brief(state, report=None, out_path=tmp_path / "pnl.json")
    payload = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert payload["open_positions_mtm_usd"] == expected_scaled
    assert payload["open_positions_mtm_usd_1x"] == expected_1x


def test_close_paper_positions_on_exit_stamps_spx_drift():
    state = {
        "paper_positions": {
            "p1": {
                "position_id": "p1",
                "status": "open",
                "spx_at_entry": 6000.0,
            }
        }
    }
    alerts = [ExitAlert("p1", "take_profit", "green", 45.0, 45.0)]
    closed = close_paper_positions_on_exit(
        state,
        alerts,
        evaluated_at="2026-06-16T14:00:00+00:00",
        logic_version="xsp_lane_a_v2",
        spx_at_exit=6120.0,
    )
    assert len(closed) == 1
    assert closed[0]["spx_at_exit"] == 6120.0
    assert closed[0]["spy_drift_pct"] == 2.0


def test_run_monitor_reaps_expired_paper_positions(tmp_path):
    state = {
        "paper_positions": {
            "paper:XSP:2026-06-13:6000": {
                "position_id": "paper:XSP:2026-06-13:6000",
                "lane": "A",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 6000.0,
                "expiration_date": "2026-06-13",
                "quantity": 1.0,
                "average_price": 2.5,
                "mark_price": 2.0,
                "entry_mid_premium": 2.4,
                "status": "open",
                "entry_ts": "2026-06-12T19:45:00+00:00",
            }
        }
    }
    save_state(tmp_path / "state.json", state)
    report = run_monitor(
        state_path=tmp_path / "state.json",
        now_et=datetime(2026, 6, 16, 9, 45, tzinfo=ET),
        publish_intel=False,
        fetch_ta=False,
        write_paper_brief=False,
    )
    refreshed = load_state(tmp_path / "state.json")
    pos = refreshed["paper_positions"]["paper:XSP:2026-06-13:6000"]
    assert report.paper_hypothetical_exits == []
    assert pos["status"] == "closed"
    assert pos["exit_reason"] == "expired"
    assert refreshed["paper_events"][-1]["exit_reason"] == "expired"


def test_run_monitor_closes_paper_positions_with_spx_drift(tmp_path, monkeypatch):
    state = {
        "paper_positions": {
            "paper:XSP:2026-07-18:6000": {
                "position_id": "paper:XSP:2026-07-18:6000",
                "lane": "A",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 6000.0,
                "expiration_date": "2026-07-18",
                "quantity": 1.0,
                "average_price": 2.5,
                "mark_price": 2.0,
                "entry_mid_premium": 2.4,
                "status": "open",
                "entry_ts": "2026-06-15T19:45:00+00:00",
                "spx_at_entry": 6000.0,
            }
        }
    }
    save_state(tmp_path / "state.json", state)
    monkeypatch.setattr(
        "xsp_killer.lane_a_monitor.refresh_paper_marks", lambda rows: rows
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_monitor.evaluate_exit_alerts",
        lambda pos, rules, now_et=None, ta_signal=None, suppress_morning_cut_dte=None: [
            ExitAlert(pos.position_id, "take_profit", "green", 45.0, 45.0)
        ],
    )
    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spx_proxy", lambda: 6120.0)
    report = run_monitor(
        state_path=tmp_path / "state.json",
        now_et=datetime(2026, 6, 16, 9, 45, tzinfo=ET),
        publish_intel=False,
        fetch_ta=False,
        write_paper_brief=False,
    )
    refreshed = load_state(tmp_path / "state.json")
    pos = refreshed["paper_positions"]["paper:XSP:2026-07-18:6000"]
    assert report.paper_hypothetical_exits[0]["position_id"] == pos["position_id"]
    assert pos["status"] == "closed"
    assert pos["spx_at_exit"] == 6120.0
    assert pos["spy_drift_pct"] == 2.0


def test_run_monitor_closes_paper_position_when_rh_read_enabled(
    tmp_path, monkeypatch
):
    position_id = "paper:XSP:2026-07-18:6000"
    state = {
        "paper_positions": {
            position_id: {
                "position_id": position_id,
                "lane": "A",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 6000.0,
                "expiration_date": "2026-07-18",
                "quantity": 1.0,
                "average_price": 2.5,
                "mark_price": 2.5,
                "entry_mid_premium": 2.5,
                "status": "open",
                "entry_ts": "2026-06-15T19:45:00+00:00",
            }
        }
    }
    save_state(tmp_path / "state.json", state)

    monkeypatch.setattr(lane_a_monitor, "rh_read_enabled", lambda: True)
    monkeypatch.setattr(
        lane_a_monitor, "fetch_robinhood_option_positions", lambda: ([], None)
    )

    def _stop_loss_mark(rows):
        return [{**row, "mark_price": 1.5} for row in rows]

    monkeypatch.setattr(lane_a_monitor, "refresh_paper_marks", _stop_loss_mark)
    monkeypatch.setattr("xsp_killer.lane_a_entry.fetch_spx_proxy", lambda: 6000.0)

    report = run_monitor(
        state_path=tmp_path / "state.json",
        now_et=datetime(2026, 6, 16, 9, 45, tzinfo=ET),
        publish_intel=False,
        fetch_ta=False,
        write_paper_brief=False,
    )

    refreshed = load_state(tmp_path / "state.json")
    position = refreshed["paper_positions"][position_id]
    assert report.rh_connected is True
    assert report.rh_poll_skipped is False
    assert report.paper_mode == "automated_paper"
    assert any(alert["exit_reason"] == "stop_loss" for alert in report.alerts)
    assert position["mark_price"] == 1.5
    assert position["status"] == "closed"
    assert position["exit_reason"] == "stop_loss"


def test_run_monitor_opens_shadow_virtual_holds(tmp_path, monkeypatch):
    state = {
        "paper_positions": {
            "paper:XSP:2026-07-18:6000": {
                "position_id": "paper:XSP:2026-07-18:6000",
                "lane": "A",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 6000.0,
                "expiration_date": "2026-07-18",
                "quantity": 1.0,
                "average_price": 100.0,
                "mark_price": 79.0,
                "entry_mid_premium": 100.0,
                "status": "open",
                "entry_ts": "2026-06-15T19:45:00+00:00",
            }
        }
    }
    save_state(tmp_path / "state.json", state)
    monkeypatch.setattr(
        "xsp_killer.lane_a_monitor.refresh_paper_marks", lambda rows: rows
    )
    report = run_monitor(
        state_path=tmp_path / "state.json",
        now_et=datetime(2026, 6, 16, 9, 0, tzinfo=ET),
        publish_intel=False,
        fetch_ta=False,
        write_paper_brief=False,
    )
    refreshed = load_state(tmp_path / "state.json")
    hold_ids = {
        row["bracket_id"] for row in refreshed.get("shadow_virtual_holds") or []
    }
    assert report.paper_hypothetical_exits[0]["exit_reason"] == "stop_loss"
    assert "wide_sl_30" in hold_ids
    assert "defer_morning_cut_1d" in hold_ids
    assert "defer_morning_cut_3d" in hold_ids
    assert "defer_morning_cut_5d" in hold_ids


def test_run_monitor_closes_shadow_virtual_holds_on_future_cycle(tmp_path, monkeypatch):
    state = {
        "shadow_virtual_holds": [
            {
                "virtual_hold_id": "vh-1",
                "opened_at": "2026-06-16T13:45:00+00:00",
                "position_id": "paper:XSP:2026-07-18:6000",
                "bracket_id": "wide_sl_30",
                "label": "Wide stop 30% (variant-style)",
                "logic_version": "xsp_lane_a_v2",
                "lane": "A",
                "chain_symbol": "XSP",
                "option_type": "call",
                "strike": 6000.0,
                "expiration_date": "2026-07-18",
                "quantity": 1.0,
                "average_price": 100.0,
                "entry_mid_premium": 100.0,
                "entry_ts": "2026-06-15T19:45:00+00:00",
                "mark_price": 84.0,
                "mark_quote_stale": False,
                "dte": 32,
                "status": "open",
            }
        ]
    }
    save_state(tmp_path / "state.json", state)

    def _mark_virtual(rows):
        updated = []
        for row in rows:
            copy = dict(row)
            copy["mark_price"] = 68.0
            copy["last_mark_price"] = 68.0
            updated.append(copy)
        return updated

    monkeypatch.setattr("xsp_killer.lane_a_monitor.refresh_paper_marks", _mark_virtual)
    run_monitor(
        state_path=tmp_path / "state.json",
        positions_override=[],
        now_et=datetime(2026, 6, 17, 10, 5, tzinfo=ET),
        publish_intel=False,
        fetch_ta=False,
        write_paper_brief=False,
    )
    refreshed = load_state(tmp_path / "state.json")
    assert refreshed.get("shadow_virtual_holds") == []
    close_evt = refreshed["paper_shadow_events"][-1]
    assert close_evt["event_type"] == "virtual_hold_closed"
    assert close_evt["bracket_id"] == "wide_sl_30"
    assert close_evt["exit_reason"] == "stop_loss"


def _mk_position(position_id: str, mark: float | None = 4.5) -> LaneAPosition:
    return LaneAPosition(
        position_id=position_id,
        chain_symbol="XSP",
        option_type="call",
        strike=600.0,
        expiration_date=date(2026, 7, 10),
        quantity=2.0,
        average_price=5.0,
        mark_price=mark,
        dte=3,
    )


def _mk_alert(position_id: str) -> ExitAlert:
    return ExitAlert(
        position_id=position_id,
        exit_reason="time_stop",
        message="time stop",
        pnl_usd=-10.0,
        pnl_per_contract=-5.0,
    )


def _force_live(monkeypatch, live: bool) -> None:
    monkeypatch.setattr(lane_a_monitor, "live_exits_enabled", lambda **k: live)
    monkeypatch.setattr(lane_a_monitor, "kill_switch_engaged", lambda: False)


def test_real_option_id_distinguishes_paper_from_uuid():
    uid = "11111111-1111-1111-1111-111111111111"
    assert _real_option_id(_mk_position(uid)) == uid
    assert _real_option_id(_mk_position("paper:XSP:2026-07-24:7550")) is None


def test_dry_run_skips_paper_and_runs_canary(monkeypatch):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    monkeypatch.setenv("XSP_LANE_A_PHASE1_CANARY", "true")
    _force_live(monkeypatch, False)

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            raise AssertionError("paper position must not be reviewed live")

        def phase1_canary_review(self, **kwargs):
            return {
                "instrument_id": "aaaa",
                "expiration_date": "2026-07-10",
                "strike_price": "600",
                "review": {"data": {"ok": True}},
            }

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    pid = "paper:XSP:2026-07-24:7550"
    out = dry_run_exit_reviews_via_mcp([_mk_alert(pid)], [_mk_position(pid)])
    assert any(r.get("skipped") for r in out)
    canary = [r for r in out if r.get("canary")]
    assert len(canary) == 1
    assert canary[0]["no_order_placed"] is True


def test_dry_run_reviews_real_position_no_place_when_off(monkeypatch):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    _force_live(monkeypatch, False)
    seen: dict[str, object] = {}

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            seen["order"] = order
            return {"data": {"ok": True}}

        def place_option_order(self, order):
            raise AssertionError("must not place when live exits are off")

        def phase1_canary_review(self, **kwargs):
            raise AssertionError("canary must not run when a real position reviews")

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    uid = "11111111-1111-1111-1111-111111111111"
    out = dry_run_exit_reviews_via_mcp([_mk_alert(uid)], [_mk_position(uid)])
    order = seen["order"]
    assert order["legs"][0]["option_id"] == uid
    assert order["legs"][0]["side"] == "sell"
    assert order["legs"][0]["position_effect"] == "close"
    assert order["quantity"] == "2"
    assert order["price"] == "4.50"
    assert not any(r.get("canary") for r in out)
    assert out[0]["live"] is False
    assert "placed" not in out[0]
    assert "review" in out[0]


def test_dry_run_places_real_exit_when_live(monkeypatch, tmp_path):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    _force_live(monkeypatch, True)
    from xsp_killer.live_gates import REQUIRED_STATEMENT
    import json

    vid = "xsp_lane_a_v2"
    ack = tmp_path / "LIVE_HUMAN_REVIEW.json"
    ack.write_text(
        json.dumps({"variant_id": vid, "statement": REQUIRED_STATEMENT}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", vid)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK", vid)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(ack))
    seen: dict[str, object] = {}

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            return {"data": {"ok": True}}

        def place_option_order(self, order):
            seen["place"] = order
            return {"data": {"id": "order-123", "state": "unconfirmed"}}

        def phase1_canary_review(self, **kwargs):
            raise AssertionError("canary must not run with a real position")

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    uid = "11111111-1111-1111-1111-111111111111"
    out = dry_run_exit_reviews_via_mcp([_mk_alert(uid)], [_mk_position(uid)])
    place = seen["place"]
    assert place["legs"][0]["side"] == "sell"
    assert place["legs"][0]["position_effect"] == "close"
    # Deterministic idempotency key for this (option, day, reason).
    assert place["ref_id"] == _exit_ref_id(
        uid, datetime.now(ET).date().isoformat(), "time_stop"
    )
    assert out[0]["live"] is True
    assert out[0]["placed"]["data"]["id"] == "order-123"


def test_variant_monitor_does_not_place_when_live_variant_id_unset(
    monkeypatch,
):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    _force_live(monkeypatch, True)
    monkeypatch.delenv("XSP_LANE_A_LIVE_VARIANT_ID", raising=False)

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            return {"data": {"ok": True}}

        def place_option_order(self, order):
            raise AssertionError("variant monitor must not place without allowlist")

        def phase1_canary_review(self, **kwargs):
            raise AssertionError("canary must not run with a real position")

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    uid = "11111111-1111-1111-1111-111111111111"
    out = dry_run_exit_reviews_via_mcp(
        [_mk_alert(uid)],
        [_mk_position(uid)],
        variant_monitor=True,
        variant_id="xsp_lane_a_v2_easy_tp",
    )
    assert out[0]["live"] is False
    assert "review" in out[0]
    assert "placed" not in out[0]


def test_variant_monitor_does_not_place_when_live_variant_id_mismatched(
    monkeypatch,
):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    _force_live(monkeypatch, True)
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", "xsp_lane_a_v2_promoted")

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            return {"data": {"ok": True}}

        def place_option_order(self, order):
            raise AssertionError("mismatched LIVE_VARIANT_ID must block place")

        def phase1_canary_review(self, **kwargs):
            raise AssertionError("canary must not run with a real position")

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    uid = "11111111-1111-1111-1111-111111111111"
    out = dry_run_exit_reviews_via_mcp(
        [_mk_alert(uid)],
        [_mk_position(uid)],
        variant_monitor=True,
        variant_id="xsp_lane_a_v2_easy_tp",
    )
    assert out[0]["live"] is False
    assert "review" in out[0]
    assert "placed" not in out[0]


def test_dry_run_kill_switch_blocks_place(monkeypatch):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    monkeypatch.setattr(lane_a_monitor, "live_exits_enabled", lambda **k: True)
    monkeypatch.setattr(lane_a_monitor, "kill_switch_engaged", lambda: True)

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            return {"data": {"ok": True}}

        def place_option_order(self, order):
            raise AssertionError("kill switch must block placement")

        def phase1_canary_review(self, **kwargs):
            raise AssertionError("canary must not run with a real position")

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    uid = "11111111-1111-1111-1111-111111111111"
    out = dry_run_exit_reviews_via_mcp([_mk_alert(uid)], [_mk_position(uid)])
    assert out[0]["live"] is False
    assert "placed" not in out[0]
    assert "review" in out[0]


def test_exit_ref_id_is_deterministic():
    uid = "11111111-1111-1111-1111-111111111111"
    a = _exit_ref_id(uid, "2026-07-07", "time_stop")
    b = _exit_ref_id(uid, "2026-07-07", "time_stop")
    c = _exit_ref_id(uid, "2026-07-08", "time_stop")
    assert a == b
    assert a != c


def test_dry_run_canary_runs_with_no_alerts(monkeypatch):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    monkeypatch.setenv("XSP_LANE_A_PHASE1_CANARY", "true")
    _force_live(monkeypatch, False)

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            raise AssertionError("no positions to review")

        def phase1_canary_review(self, **kwargs):
            return {"instrument_id": "aaaa", "review": {"data": {"ok": True}}}

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    out = dry_run_exit_reviews_via_mcp([], [])
    assert len(out) == 1
    assert out[0]["canary"] is True


def test_dry_run_disabled_when_mcp_off(monkeypatch):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: False)
    assert dry_run_exit_reviews_via_mcp([], []) == []


def test_dry_run_canary_disabled_by_flag(monkeypatch):
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    monkeypatch.setenv("XSP_LANE_A_PHASE1_CANARY", "false")
    _force_live(monkeypatch, False)

    class FakeAdapter:
        config = None

        def review_option_order(self, order):
            raise AssertionError("paper must not review")

        def phase1_canary_review(self, **kwargs):
            raise AssertionError("canary disabled")

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    pid = "paper:XSP:2026-07-24:7550"
    out = dry_run_exit_reviews_via_mcp([_mk_alert(pid)], [_mk_position(pid)])
    assert any(r.get("skipped") for r in out)
    assert not any(r.get("canary") for r in out)


def test_variant_monitor_skips_mcp_canary_when_idle(tmp_path, monkeypatch):
    """Variant path (write_paper_brief=False) skips canary with no alerts/RH positions."""
    monkeypatch.setattr(lane_a_monitor, "rh_mcp_enabled", lambda: True)
    monkeypatch.setenv("XSP_LANE_A_PHASE1_CANARY", "true")
    save_state(tmp_path / "state.json", {"paper_positions": {}})

    class FakeAdapter:
        config = None

        def phase1_canary_review(self, **kwargs):
            raise AssertionError("variant idle path must skip canary")

        def review_option_order(self, order):
            raise AssertionError("no reviews expected")

    monkeypatch.setattr(lane_a_monitor, "RobinhoodMCPAdapter", FakeAdapter)
    report = run_monitor(
        state_path=tmp_path / "state.json",
        now_et=datetime(2026, 6, 16, 9, 45, tzinfo=ET),
        publish_intel=False,
        fetch_ta=False,
        write_paper_brief=False,
    )
    assert report.rh_mcp_reviews == []


# --- Dip-buy swing: DIP_BOUNCE gate + swing-hold exits -----------------------

import dataclasses  # noqa: E402

from xsp_killer.lane_a_monitor import regime_gate_allows  # noqa: E402

SWING_RULES = LaneRules(
    lane="A",
    dte_min=14,
    dte_max=60,
    exclude_expiry_month=("01",),
    chain_symbols=("SPX", "XSP"),
    stop_loss_pct=0.50,
    take_profit_pct=0.40,
    sell_eval_start_et=time(8, 0),
    sell_deadline_et=time(9, 30),
    no_sell_start_et=time(0, 0),
    no_sell_end_et=time(8, 0),
    require_upper_bb_for_take_profit=False,
    logic_version="xsp_lane_a_v2_dip_swing_14dte",
    regime_gate="DIP_BOUNCE",
    swing_hold=True,
    max_hold_dte=2,
)


def _swing_pos(avg: float, mark: float, dte: int) -> LaneAPosition:
    pos = LaneAPosition(
        position_id="paper:XSP:2026-07-10:600",
        chain_symbol="XSP",
        option_type="call",
        strike=600.0,
        expiration_date=date(2026, 7, 10),
        quantity=1.0,
        average_price=avg,
        mark_price=mark,
        dte=dte,
    )
    pos.entry_ts = "2026-06-19T19:45:00+00:00"  # prior day
    return pos


def test_dip_bounce_gate_requires_confirmed_bounce():
    # Buys weakness (RED/YELLOW) as long as the bounce is confirmed.
    ok, _ = regime_gate_allows(
        regime_gate="DIP_BOUNCE",
        regime="RED",
        regime_ok=False,
        yellow_frac=None,
        ta_entry_ok=True,
    )
    assert ok is True
    # No bounce -> blocked even in a green tape.
    ok, reason = regime_gate_allows(
        regime_gate="DIP_BOUNCE",
        regime="GREEN",
        regime_ok=True,
        yellow_frac=None,
        ta_entry_ok=False,
    )
    assert ok is False
    assert "bounce" in (reason or "").lower()


def test_swing_hold_does_not_time_stop_across_days():
    # Small green, far from expiry — no clock forced cut for swing or baseline.
    pos = _swing_pos(avg=5.0, mark=5.1, dte=20)
    now = datetime(2026, 6, 19, 10, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, SWING_RULES, now_et=now)
    assert not any(a.exit_reason == "time_stop" for a in alerts)
    non_swing = dataclasses.replace(SWING_RULES, swing_hold=False)
    alerts_ns = evaluate_exit_alerts(pos, non_swing, now_et=now)
    assert not any(a.exit_reason == "time_stop" for a in alerts_ns)


def test_swing_hold_takes_profit_intraday_outside_window():
    pos = _swing_pos(avg=5.0, mark=7.0, dte=20)  # +40%
    now = datetime(2026, 6, 19, 13, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, SWING_RULES, now_et=now)
    assert any(a.exit_reason == "take_profit" for a in alerts)
    # Baseline now also takes profit anytime session is open (no clock gate).
    non_swing = dataclasses.replace(SWING_RULES, swing_hold=False, require_upper_bb_for_take_profit=False)
    alerts_ns = evaluate_exit_alerts(pos, non_swing, now_et=now)
    assert any(a.exit_reason == "take_profit" for a in alerts_ns)


def test_swing_hold_stop_loss_fires_anytime():
    pos = _swing_pos(avg=5.0, mark=2.5, dte=20)  # -50%
    now = datetime(2026, 6, 19, 13, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, SWING_RULES, now_et=now)
    assert any(a.exit_reason == "stop_loss" for a in alerts)


def test_swing_hold_near_expiry_cut():
    now = datetime(2026, 6, 19, 13, 0, tzinfo=ET)
    # DTE at the cutoff -> force close.
    near = _swing_pos(avg=5.0, mark=4.9, dte=2)
    alerts = evaluate_exit_alerts(near, SWING_RULES, now_et=now)
    assert any(a.exit_reason == "time_stop" for a in alerts)
    # Still comfortably before expiry -> keep holding.
    far = _swing_pos(avg=5.0, mark=4.9, dte=5)
    alerts_far = evaluate_exit_alerts(far, SWING_RULES, now_et=now)
    assert alerts_far == []


def test_swing_hold_stop_loss_fires_when_mark_stale():
    pos = _swing_pos(avg=5.0, mark=2.5, dte=20)  # -50% SL hit
    pos.mark_quote_stale = True
    pos.pnl_per_contract = -250.0
    pos.pnl_usd = -250.0
    now = datetime(2026, 6, 19, 13, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, SWING_RULES, now_et=now)
    assert any(a.exit_reason == "stop_loss" for a in alerts)


def test_swing_hold_stop_loss_fires_in_gth():
    pos = _swing_pos(avg=5.0, mark=2.5, dte=20)  # -50% SL hit
    pos.pnl_per_contract = -250.0
    pos.pnl_usd = -250.0
    now = datetime(2026, 6, 19, 7, 30, tzinfo=ET)  # GTH morning
    alerts = evaluate_exit_alerts(pos, SWING_RULES, now_et=now)
    assert any(a.exit_reason == "stop_loss" for a in alerts)


def test_swing_hold_take_profit_suppressed_when_mark_stale():
    pos = _swing_pos(avg=5.0, mark=7.0, dte=20)  # +40% TP hit
    pos.mark_quote_stale = True
    pos.pnl_per_contract = 200.0
    pos.pnl_usd = 200.0
    now = datetime(2026, 6, 19, 13, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, SWING_RULES, now_et=now)
    assert not any(
        a.exit_reason in ("take_profit", "upper_bb_rejection") for a in alerts
    )


def test_swing_hold_near_expiry_cut_still_fires():
    pos = _swing_pos(avg=5.0, mark=4.9, dte=2)  # dte == max_hold_dte
    pos.pnl_per_contract = -10.0
    pos.pnl_usd = -10.0
    now = datetime(2026, 6, 19, 13, 0, tzinfo=ET)
    alerts = evaluate_exit_alerts(pos, SWING_RULES, now_et=now)
    assert any(a.exit_reason == "time_stop" for a in alerts)
