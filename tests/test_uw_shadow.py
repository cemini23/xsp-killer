"""Unit tests for TipDrop UW Advanced shadow overlay (no network)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from xsp_killer import uw_shadow
from xsp_killer.uw_shadow import (
    build_darkpool_summary,
    build_flow_summary,
    build_gex_levels_summary,
    build_iv_rank_summary,
    build_monitor_uw_shadow,
    build_net_prem_summary,
)

ET = ZoneInfo("America/New_York")


class _FakeProvider:
    def get_flow_alerts(self, ticker: str, limit: int = 100):
        return [
            {
                "type": "CALL",
                "total_premium": 250_000,
                "strike": 600.0,
                "expiry": "2026-07-18",
                "has_sweep": True,
            },
            {
                "type": "PUT",
                "total_premium": 100_000,
                "strike": 590.0,
                "expiry": "2026-07-18",
                "has_sweep": False,
            },
            {
                "type": "CALL",
                "total_premium": 50_000,
                "strike": 605.0,
                "expiry": "2026-07-25",
                "has_sweep": False,
            },
        ]

    def get_darkpool_prints(self, ticker: str, limit: int = 200, **kwargs):
        return [
            {"notional": 1_000_000, "side": "BUY"},
            {"notional": 500_000, "side": "SELL"},
        ]

    def _request(self, path, params=None, **kwargs):
        if "net-prem-ticks" in path:
            return {
                "data": [
                    {
                        "tape_time": "09:31:00",
                        "net_call_premium": "1000.5",
                        "net_put_premium": "-200.25",
                    },
                    {
                        "tape_time": "09:32:00",
                        "net_call_premium": "500",
                        "net_put_premium": "100",
                    },
                ]
            }
        if "gex-levels" in path:
            return {
                "data": [
                    {
                        "gamma_wall": "600.0",
                        "call_wall": "605",
                        "put_wall": "590",
                        "strike": "600",
                    },
                ]
            }
        return {"data": []}

    def get_iv_rank_uw(self, ticker):
        return {"iv_rank_1y": "42.95", "volatility": "0.18"}


def test_uw_shadow_disabled_by_default(monkeypatch):
    monkeypatch.delenv("XSP_UW_SHADOW", raising=False)
    assert build_monitor_uw_shadow() is None


def test_uw_shadow_bad_tipdrop_root_fail_open(monkeypatch, tmp_path):
    monkeypatch.setenv("XSP_UW_SHADOW", "true")
    monkeypatch.setenv("XSP_UW_TIPDROP_ROOT", str(tmp_path / "missing_tipdrop"))
    # Clear any cached TipDrop provider singleton side effects via path miss.
    assert build_monitor_uw_shadow() is None


def test_build_flow_summary_shape():
    summary = build_flow_summary(_FakeProvider(), ticker="SPY")
    assert summary is not None
    assert summary["ticker"] == "SPY"
    assert summary["n_alerts"] == 3
    assert summary["call_prem"] == 300_000.0
    assert summary["put_prem"] == 100_000.0
    assert summary["net_prem_bias"] == "call"
    assert summary["biggest_alert"]["premium"] == 250_000.0
    assert summary["biggest_alert"]["has_sweep"] is True


def test_build_net_prem_summary_shape():
    summary = build_net_prem_summary(_FakeProvider(), ticker="SPY")
    assert summary is not None
    assert summary["n_ticks"] == 2
    assert summary["net_call_prem"] == 1500.5
    assert summary["net_put_prem"] == -100.25
    assert summary["net_prem"] == 1600.75
    assert summary["net_prem_bias"] == "call"
    assert summary["last_tape_time"] == "09:32:00"


def test_build_net_prem_summary_no_request_attr():
    assert build_net_prem_summary(object()) is None


def test_build_net_prem_summary_empty_data():
    class _Empty:
        def _request(self, path, params=None, **kwargs):
            return {"data": []}

    assert build_net_prem_summary(_Empty()) is None


def test_build_iv_rank_summary():
    summary = build_iv_rank_summary(_FakeProvider(), ticker="SPY")
    assert summary is not None
    assert summary["iv_rank_1y"] == 42.95


def test_build_iv_rank_summary_fallback_key():
    class _Fallback:
        def get_iv_rank_uw(self, ticker):
            return {"iv_rank": "33.1"}

    summary = build_iv_rank_summary(_Fallback(), ticker="SPY")
    assert summary is not None
    assert summary["iv_rank_1y"] == 33.1


def test_build_gex_levels_summary_shape():
    summary = build_gex_levels_summary(_FakeProvider(), ticker="SPY")
    assert summary is not None
    assert summary["n_rows"] == 1
    assert summary["latest_raw"] is not None
    assert summary["gamma_wall"] == 600.0
    assert summary["call_wall"] == 605.0
    assert summary["put_wall"] == 590.0


def test_build_gex_levels_403_falls_back(monkeypatch):
    class _NoneRequest(_FakeProvider):
        def _request(self, path, params=None, **kwargs):
            return None

    monkeypatch.setenv("XSP_UW_SHADOW", "true")
    monkeypatch.delenv("XSP_UW_SHADOW_DARKPOOL", raising=False)
    monkeypatch.setattr(uw_shadow, "_get_provider", lambda: _NoneRequest())
    monkeypatch.setattr(
        uw_shadow,
        "build_gex_summary",
        lambda *a, **k: {"wall_side": "call"},
    )

    out = build_monitor_uw_shadow(
        now_et=datetime(2026, 7, 15, 10, 0, tzinfo=ET),
    )
    assert out is not None
    assert out["gex"] == {"wall_side": "call"}
    assert out["gex_levels"] is None


def test_build_monitor_uw_shadow_shape(monkeypatch):
    monkeypatch.setenv("XSP_UW_SHADOW", "true")
    monkeypatch.delenv("XSP_UW_SHADOW_DARKPOOL", raising=False)
    monkeypatch.setattr(uw_shadow, "_get_provider", lambda: _FakeProvider())
    monkeypatch.setattr(uw_shadow, "build_gex_summary", lambda *a, **k: None)

    out = build_monitor_uw_shadow(
        now_et=datetime(2026, 7, 15, 10, 0, tzinfo=ET),
    )
    assert out is not None
    assert out["shadow_only"] is True
    assert out["source"] == "uw_advanced"
    assert "fetched_at" in out
    assert out["flow"]["net_prem_bias"] == "call"
    assert "darkpool" not in out
    assert "net_prem" in out
    assert "iv_rank" in out
    assert "gex_levels" in out
    assert out["net_prem"]["net_prem_bias"] == "call"
    assert out["iv_rank"]["iv_rank_1y"] == 42.95


def test_darkpool_gated_off_by_default(monkeypatch):
    monkeypatch.delenv("XSP_UW_SHADOW_DARKPOOL", raising=False)
    assert build_darkpool_summary(_FakeProvider()) is None


def test_darkpool_enabled_when_flagged(monkeypatch):
    monkeypatch.setenv("XSP_UW_SHADOW_DARKPOOL", "true")
    summary = build_darkpool_summary(_FakeProvider(), ticker="SPY")
    assert summary is not None
    assert summary["n_prints"] == 2
    assert summary["total_notional"] == 1_500_000.0
    assert summary["buy_prints"] == 1
    assert summary["sell_prints"] == 1


def test_run_monitor_uw_shadow_raise_fail_open(tmp_path, monkeypatch):
    from xsp_killer.lane_a_monitor import run_monitor

    monkeypatch.setattr(
        "xsp_killer.lane_a_monitor.rh_read_enabled",
        lambda: False,
    )

    def _boom(**kwargs):
        raise RuntimeError("uw unavailable")

    monkeypatch.setattr(
        "xsp_killer.uw_shadow.build_monitor_uw_shadow",
        _boom,
    )
    report = run_monitor(
        state_path=tmp_path / "state.json",
        positions_override=[],
        publish_intel=False,
        write_paper_brief=False,
        fetch_ta=False,
    )
    assert report.uw_shadow is None
    assert report.phase == 0
