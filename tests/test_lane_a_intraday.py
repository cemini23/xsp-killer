"""Intraday cycle — max_open stacking vs early-return."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from xsp_killer.lane_a_intraday import run_intraday_cycle

ET = ZoneInfo("America/New_York")


def _write_rules(path: Path, *, max_open: int = 2, intraday: bool = True) -> None:
    data = {
        "logging": {"logic_version": "test_intraday"},
        "paper_entry": {
            "max_open_positions": max_open,
            "quantity": 1,
            "chain_symbol": "XSP",
        },
        "ta": {
            "entry": {"intraday_enabled": intraday},
        },
        "exit": {"stop_loss_pct": 0.2, "take_profit_pct": 0.3},
        "dte_min": 14,
        "dte_max": 60,
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_intraday_continues_to_entry_when_room_under_max_open(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    state = tmp_path / "state.json"
    _write_rules(rules, max_open=2)
    state.write_text(
        '{"paper_positions":{"paper:1":{"status":"open","quantity":1,'
        '"expiration_date":"2026-08-15","chain_symbol":"XSP",'
        '"option_type":"call","strike":6000,"average_price":2.0,'
        '"position_id":"paper:1"}}}',
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_monitor(**kwargs):
        calls.append("monitor")

        class R:
            alerts = []

            def to_dict(self):
                return {}

        return R()

    def fake_entry(**kwargs):
        calls.append("entry")

        class D:
            entered = False
            skip_reason = "forced_skip_for_test"
            errors = []

        return D()

    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.run_monitor", fake_monitor
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.run_paper_entry", fake_entry
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.evaluate_ta_signals",
        lambda *a, **k: type(
            "T",
            (),
            {
                "signal": "bounce",
                "entry_ok": True,
                "detail": "ok",
                "to_dict": lambda self: {},
            },
        )(),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.xsp_session_open", lambda now: True
    )
    monkeypatch.setattr("xsp_killer.lane_a_intraday.in_rth", lambda now: True)
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.write_report", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday._write_intraday_brief", lambda *a, **k: None
    )

    now = datetime(2026, 7, 20, 11, 0, tzinfo=ET)
    report = run_intraday_cycle(
        rules_path=rules, state_path=state, now_et=now, publish_intel=False
    )
    assert "monitor" in calls
    assert "entry" in calls
    assert report.entry_attempted is True


def test_intraday_stops_after_exits_when_at_max_open(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    state = tmp_path / "state.json"
    _write_rules(rules, max_open=1)
    state.write_text(
        '{"paper_positions":{"paper:1":{"status":"open","quantity":1,'
        '"expiration_date":"2026-08-15","chain_symbol":"XSP",'
        '"option_type":"call","strike":6000,"average_price":2.0,'
        '"position_id":"paper:1"}}}',
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_monitor(**kwargs):
        calls.append("monitor")

        class R:
            alerts = []

            def to_dict(self):
                return {}

        return R()

    def fake_entry(**kwargs):
        calls.append("entry")
        raise AssertionError("must not enter when at max_open")

    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.run_monitor", fake_monitor
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.run_paper_entry", fake_entry
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.evaluate_ta_signals",
        lambda *a, **k: type(
            "T",
            (),
            {
                "signal": "bounce",
                "entry_ok": True,
                "detail": "ok",
                "to_dict": lambda self: {},
            },
        )(),
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.xsp_session_open", lambda now: True
    )
    monkeypatch.setattr("xsp_killer.lane_a_intraday.in_rth", lambda now: True)
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday.write_report", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_intraday._write_intraday_brief", lambda *a, **k: None
    )

    now = datetime(2026, 7, 20, 11, 0, tzinfo=ET)
    report = run_intraday_cycle(
        rules_path=rules, state_path=state, now_et=now, publish_intel=False
    )
    assert calls == ["monitor"]
    assert report.entry_attempted is False
