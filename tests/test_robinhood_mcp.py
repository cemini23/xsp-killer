"""Tests for Robinhood Agentic MCP adapter (mocked — no live RH)."""

from __future__ import annotations

import json

import pytest

from xsp_killer.rh_broker import fetch_robinhood_option_positions, rh_read_enabled
from xsp_killer.robinhood_mcp import (
    RhMcpAccountRejected,
    RhMcpConfig,
    RhMcpError,
    RhMcpLiveExitsDisabled,
    RobinhoodMCPAdapter,
    live_exits_enabled,
    normalize_mcp_position,
    parse_mcp_http_response,
    rh_mcp_enabled,
)


def test_rh_b_poll_separate_from_lane_a(monkeypatch):
    monkeypatch.delenv("XSP_LANE_A_RH_POLL", raising=False)
    monkeypatch.delenv("XSP_LANE_B_RH_POLL", raising=False)
    monkeypatch.delenv("XSP_LANE_A_RH_MCP", raising=False)

    from xsp_killer.rh_broker import rh_poll_enabled, rh_read_enabled

    assert rh_poll_enabled(lane="a") is False
    assert rh_poll_enabled(lane="b") is False
    assert rh_read_enabled(lane="b") is False

    monkeypatch.setenv("XSP_LANE_A_RH_POLL", "true")
    assert rh_poll_enabled(lane="a") is True
    assert rh_poll_enabled(lane="b") is True  # back-compat fallback

    monkeypatch.setenv("XSP_LANE_A_RH_POLL", "false")
    monkeypatch.setenv("XSP_LANE_B_RH_POLL", "true")
    assert rh_poll_enabled(lane="a") is False
    assert rh_poll_enabled(lane="b") is True


def test_rh_mcp_disabled_by_default(monkeypatch):
    monkeypatch.delenv("XSP_LANE_A_RH_MCP", raising=False)
    assert rh_mcp_enabled() is False
    assert rh_read_enabled() is False


def test_live_exits_disabled_by_default(monkeypatch):
    monkeypatch.delenv("XSP_LANE_A_LIVE_EXITS", raising=False)
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    cfg = RhMcpConfig(agentic_account_id="", live_exits=False)
    assert live_exits_enabled(config=cfg) is False


def test_live_exits_requires_agentic_account(monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    cfg = RhMcpConfig(agentic_account_id="", live_exits=False)
    assert live_exits_enabled(config=cfg) is False


def test_fetch_mcp_not_ready_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("XSP_LANE_A_RH_MCP", "true")
    token = tmp_path / "token.json"
    cfg = RhMcpConfig(token_path=token)
    monkeypatch.setattr(
        "xsp_killer.robinhood_mcp.RhMcpConfig.load", lambda path=None: cfg
    )
    rows, err = fetch_robinhood_option_positions()
    assert rows == []
    assert err and "token missing" in err


def test_normalize_mcp_position():
    row = normalize_mcp_position(
        {
            "underlying_symbol": "XSP",
            "type": "call",
            "strike": 7500,
            "expiration": "2026-07-18",
            "qty": 1,
            "mark": 6.5,
            "instrument_id": "abc123",
        }
    )
    assert row["chain_symbol"] == "XSP"
    assert row["type"] == "call"
    assert row["strike_price"] == 7500
    assert row["_source"] == "rh_mcp"


def test_normalize_mcp_position_preserves_zero_mark():
    row = normalize_mcp_position(
        {
            "chain_symbol": "XSP",
            "type": "call",
            "strike_price": 7500,
            "mark_price": 0.0,
            "adjusted_mark_price": 1.5,
        }
    )
    assert row["mark_price"] == 0.0


def test_parse_mcp_http_response_sse():
    body = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,'
        '"result":{"content":[{"type":"text","text":"{}"}]}}\n'
    )
    parsed = parse_mcp_http_response(body)
    assert parsed["id"] == 1


def test_get_option_chains_uses_underlying_symbol(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    cfg = RhMcpConfig(token_path=token, audit_log=tmp_path / "audit.jsonl")
    seen: dict[str, object] = {}

    def fake_http(url, body, headers):
        payload = json.loads(body.decode("utf-8"))
        seen.update(payload["params"]["arguments"])
        return {
            "result": {
                "structuredContent": {
                    "data": {
                        "chains": [
                            {
                                "id": "chain-1",
                                "symbol": "XSP",
                                "can_open_position": True,
                                "expiration_dates": ["2026-07-18"],
                            }
                        ]
                    }
                }
            }
        }

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    chain = adapter.get_option_chains("xsp")
    assert seen == {"underlying_symbol": "XSP"}
    assert "chain_symbol" not in seen
    assert chain["symbol"] == "XSP"
    assert chain["expiration_dates"] == ["2026-07-18"]


def test_adapter_get_positions_mocked(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "test-token"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
    )

    def fake_http(url, body, headers):
        assert headers["Authorization"] == "Bearer test-token"
        return {
            "result": {
                "structuredContent": [
                    {
                        "chain_symbol": "XSP",
                        "type": "call",
                        "strike_price": 7500,
                        "expiration_date": "2026-07-18",
                        "quantity": 2,
                        "mark_price": 5.0,
                    }
                ]
            }
        }

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    rows = adapter.get_open_option_positions()
    assert len(rows) == 1
    assert rows[0]["chain_symbol"] == "XSP"
    assert audit.is_file()
    assert "get_option_positions" in audit.read_text(encoding="utf-8")


def test_place_order_blocked_when_live_exits_off(tmp_path, monkeypatch):
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=False,
    )

    def fake_http(url, body, headers):
        return {"result": {"structuredContent": {"ok": True}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    with pytest.raises(RhMcpLiveExitsDisabled):
        adapter.place_option_order(
            {
                "quantity": 1,
                "side": "sell",
                "option_id": "opt-1",
                "position_effect": "close",
            }
        )
    audit_rows = [json.loads(line) for line in audit.read_text().splitlines()]
    deny = audit_rows[-1]
    assert deny["event"] == "deny"
    assert deny["invariant"] == "I7"
    assert deny["principal"]["agentic_account_id"] == "agentic-1"


def test_place_order_rejects_unknown_position_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=False,
    )
    adapter = RobinhoodMCPAdapter(
        config=cfg, http_post=lambda *a: {"result": {"structuredContent": {"ok": True}}}
    )
    with pytest.raises(RhMcpError, match="position_effect"):
        adapter.place_option_order(
            {
                "account_number": "agentic-1",
                "legs": [
                    {
                        "option_id": "opt-1",
                        "side": "sell",
                        "position_effect": "opne",
                    }
                ],
                "quantity": "1",
            }
        )
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["event"] == "deny"
    assert deny["invariant"] == "I7"


def test_place_order_rejects_empty_position_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=False,
    )
    adapter = RobinhoodMCPAdapter(
        config=cfg, http_post=lambda *a: {"result": {"structuredContent": {"ok": True}}}
    )
    with pytest.raises(RhMcpError, match="position_effect"):
        adapter.place_option_order(
            {"quantity": 1, "side": "sell", "option_id": "opt-1"}
        )
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["event"] == "deny"
    assert deny["invariant"] == "I7"


def test_place_order_denied_without_pinned_account(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="",
        live_exits=True,
        require_review_before_place=False,
    )
    adapter = RobinhoodMCPAdapter(
        config=cfg, http_post=lambda *a: {"result": {"structuredContent": {"ok": True}}}
    )
    with pytest.raises(RhMcpAccountRejected):
        adapter.place_option_order(
            {
                "legs": [
                    {
                        "option_id": "opt-1",
                        "side": "sell",
                        "position_effect": "close",
                    }
                ],
                "quantity": "1",
            }
        )
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["event"] == "deny"
    assert deny["invariant"] == "I3"


def test_place_order_requires_matching_review_grant(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=True,
    )

    def fake_http(url, body, headers):
        return {"result": {"structuredContent": {"ok": True}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    with pytest.raises(RhMcpError):
        adapter.place_option_order(
            {
                "quantity": 1,
                "side": "sell",
                "option_id": "x",
                "position_effect": "close",
            }
        )
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["invariant"] == "I2"


def test_review_grant_allows_matching_place(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    cfg = RhMcpConfig(
        token_path=token,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=True,
    )
    order = {
        "quantity": 1,
        "side": "sell",
        "option_id": "opt-1",
        "position_effect": "close",
    }

    def fake_http(url, body, headers):
        return {"result": {"structuredContent": {"ok": True}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    adapter.review_option_order(order)
    result = adapter.place_option_order(dict(order))
    assert result == {"ok": True}


def test_review_grant_allows_matching_place_legs_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    cfg = RhMcpConfig(
        token_path=token,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=True,
    )
    order = {
        "account_number": "agentic-1",
        "legs": [{"option_id": "opt-1", "side": "sell", "position_effect": "close"}],
        "type": "limit",
        "quantity": "1",
        "price": "5.00",
    }

    def fake_http(url, body, headers):
        return {"result": {"structuredContent": {"ok": True}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    adapter.review_option_order(order)
    result = adapter.place_option_order(dict(order))
    assert result == {"ok": True}


def test_place_order_account_number_pin_rejects_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=False,
    )

    def fake_http(url, body, headers):
        return {"result": {"structuredContent": {"ok": True}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    order = {
        "account_number": "not-agentic",
        "legs": [{"option_id": "opt-1", "side": "sell", "position_effect": "close"}],
        "type": "market",
        "quantity": "1",
    }
    with pytest.raises(Exception):
        adapter.place_option_order(order)
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["invariant"] == "I3"


def test_ratio_quantity_counts_toward_max_contracts(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=False,
        max_contracts_per_order=2,
    )

    def fake_http(url, body, headers):
        return {"result": {"structuredContent": {"ok": True}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    order = {
        "account_number": "agentic-1",
        "legs": [
            {
                "option_id": "opt-1",
                "side": "sell",
                "position_effect": "close",
                "ratio_quantity": 3,
            }
        ],
        "type": "market",
        "quantity": "1",
    }
    with pytest.raises(RhMcpError):
        adapter.place_option_order(order)
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["invariant"] == "I5"


def test_kill_switch_blocks_place_even_when_live(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    monkeypatch.setenv("XSP_LANE_A_KILL_SWITCH", "true")
    from xsp_killer.robinhood_mcp import RhMcpKillSwitch

    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=False,
    )

    def fake_http(url, body, headers):
        return {"result": {"structuredContent": {"ok": True}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    order = {
        "account_number": "agentic-1",
        "legs": [{"option_id": "opt-1", "side": "sell", "position_effect": "close"}],
        "type": "market",
        "quantity": "1",
    }
    with pytest.raises(RhMcpKillSwitch):
        adapter.place_option_order(order)
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["invariant"] == "I8"


def test_kill_switch_file_engages(tmp_path, monkeypatch):
    from xsp_killer.robinhood_mcp import kill_switch_engaged

    monkeypatch.delenv("XSP_LANE_A_KILL_SWITCH", raising=False)
    kill_file = tmp_path / "KILL_SWITCH"
    monkeypatch.setenv("XSP_LANE_A_KILL_FILE", str(kill_file))
    assert kill_switch_engaged() is False
    kill_file.write_text("halt", encoding="utf-8")
    assert kill_switch_engaged() is True


def test_kill_switch_file_oserror_fails_closed(tmp_path, monkeypatch):
    from pathlib import Path

    from xsp_killer.robinhood_mcp import kill_switch_engaged

    monkeypatch.delenv("XSP_LANE_A_KILL_SWITCH", raising=False)
    monkeypatch.setenv("XSP_LANE_A_KILL_FILE", str(tmp_path / "KILL_SWITCH"))

    def boom_exists(self):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "exists", boom_exists)
    assert kill_switch_engaged() is True


def test_review_with_warnings_does_not_grant_place(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=True,
    )
    order = {
        "account_number": "agentic-1",
        "legs": [{"option_id": "opt-1", "side": "sell", "position_effect": "close"}],
        "quantity": "1",
    }

    def fake_http(url, body, headers):
        return {
            "result": {
                "structuredContent": {"ok": True, "warnings": ["thin_liquidity"]}
            }
        }

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    adapter.review_option_order(order)
    assert adapter._active_grant is None
    assert adapter._last_review is not None
    with pytest.raises(RhMcpError, match="prior review_option_order"):
        adapter.place_option_order(dict(order))
    events = [json.loads(line)["event"] for line in audit.read_text().splitlines()]
    assert "review_rejected" in events


def test_review_rejection_blocks_place_grant(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=True,
    )
    order = {
        "account_number": "agentic-1",
        "legs": [{"option_id": "opt-1", "side": "sell", "position_effect": "close"}],
        "quantity": "1",
    }

    def fake_http(url, body, headers):
        return {
            "result": {
                "structuredContent": {
                    "rejected": True,
                    "rejection_reason": "insufficient buying power",
                }
            }
        }

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    adapter.review_option_order(order)
    assert adapter._active_grant is None
    deny = [
        json.loads(line)
        for line in audit.read_text().splitlines()
        if json.loads(line).get("event") == "review_rejected"
    ]
    assert deny and deny[-1]["invariant"] == "I2"
    with pytest.raises(RhMcpError, match="prior review_option_order"):
        adapter.place_option_order(dict(order))


def test_review_failed_order_checks_blocks_grant(tmp_path, monkeypatch):
    monkeypatch.setenv("XSP_LANE_A_LIVE_EXITS", "true")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        require_review_before_place=True,
    )
    order = {
        "account_number": "agentic-1",
        "legs": [{"option_id": "opt-1", "side": "sell", "position_effect": "close"}],
        "quantity": "1",
    }

    def fake_http(url, body, headers):
        return {
            "result": {
                "structuredContent": {
                    "ok": True,
                    "order_checks": [{"status": "fail", "code": "OPTION_NO_BID_PRICE"}],
                }
            }
        }

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    adapter.review_option_order(order)
    assert adapter._active_grant is None
    events = [json.loads(line) for line in audit.read_text().splitlines()]
    assert any(
        row.get("event") == "review_rejected" and row.get("invariant") == "I2"
        for row in events
    )


def test_phase1_canary_review_previews_without_placing(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=tmp_path / "audit.jsonl",
        agentic_account_id="agentic-1",
    )
    calls: list[str] = []

    def fake_http(url, body, headers):
        payload = json.loads(body.decode("utf-8"))
        name = payload["params"]["name"]
        calls.append(name)
        if name == "get_option_instruments":
            return {
                "result": {
                    "structuredContent": {
                        "data": {
                            "results": [
                                {
                                    "id": "11111111-1111-1111-1111-111111111111",
                                    "type": "call",
                                    "tradability": "tradable",
                                    "strike_price": "610",
                                    "expiration_date": "2026-07-10",
                                },
                                {
                                    "id": "22222222-2222-2222-2222-222222222222",
                                    "type": "call",
                                    "tradability": "tradable",
                                    "strike_price": "605",
                                    "expiration_date": "2026-07-08",
                                },
                            ]
                        }
                    }
                }
            }
        if name == "review_option_order":
            args = payload["params"]["arguments"]
            return {
                "result": {
                    "structuredContent": {"data": {"ok": True, "legs": args["legs"]}}
                }
            }
        return {"result": {"structuredContent": {}}}

    adapter = RobinhoodMCPAdapter(config=cfg, http_post=fake_http)
    out = adapter.phase1_canary_review()
    assert "review_option_order" in calls
    assert "place_option_order" not in calls
    # Soonest expiry wins.
    assert out["expiration_date"] == "2026-07-08"
    assert out["instrument_id"] == "22222222-2222-2222-2222-222222222222"


def test_rh_mcp_config_loads_yaml(tmp_path, monkeypatch):
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    yaml_path = tmp_path / "rh_mcp.yaml"
    yaml_path.write_text(
        "agentic_account_id: 'acct-99'\nmax_contracts_per_order: 2\n",
        encoding="utf-8",
    )
    cfg = RhMcpConfig.load(yaml_path)
    assert cfg.agentic_account_id == "acct-99"
    assert cfg.max_contracts_per_order == 2


# --- Live entries: separate gate from exits ---------------------------------


def test_live_entries_disabled_by_default(monkeypatch):
    from xsp_killer.robinhood_mcp import live_entries_enabled

    monkeypatch.delenv("XSP_LANE_A_LIVE_ENTRIES", raising=False)
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    cfg = RhMcpConfig(agentic_account_id="", live_entries=False)
    assert live_entries_enabled(config=cfg) is False


def test_open_leg_blocked_when_only_exits_enabled(tmp_path, monkeypatch):
    """A buy-to-open must be gated by LIVE_ENTRIES, not LIVE_EXITS."""
    monkeypatch.delenv("XSP_LANE_A_LIVE_ENTRIES", raising=False)
    monkeypatch.delenv("XSP_LANE_A_LIVE_EXITS", raising=False)
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=True,
        live_entries=False,
        require_review_before_place=False,
    )
    adapter = RobinhoodMCPAdapter(
        config=cfg, http_post=lambda *a: {"result": {"structuredContent": {"ok": 1}}}
    )
    order = {
        "account_number": "agentic-1",
        "legs": [{"option_id": "o1", "side": "buy", "position_effect": "open"}],
        "type": "limit",
        "quantity": "1",
        "price": "1.00",
    }
    with pytest.raises(RhMcpLiveExitsDisabled):
        adapter.place_option_order(order)
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["invariant"] == "I7"


def test_close_leg_blocked_when_only_entries_enabled(tmp_path, monkeypatch):
    """A sell-to-close must stay gated by LIVE_EXITS even if entries are on."""
    monkeypatch.delenv("XSP_LANE_A_LIVE_ENTRIES", raising=False)
    monkeypatch.delenv("XSP_LANE_A_LIVE_EXITS", raising=False)
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    cfg = RhMcpConfig(
        token_path=token,
        audit_log=audit,
        agentic_account_id="agentic-1",
        live_exits=False,
        live_entries=True,
        require_review_before_place=False,
    )
    adapter = RobinhoodMCPAdapter(
        config=cfg, http_post=lambda *a: {"result": {"structuredContent": {"ok": 1}}}
    )
    order = {
        "account_number": "agentic-1",
        "legs": [{"option_id": "o1", "side": "sell", "position_effect": "close"}],
        "type": "limit",
        "quantity": "1",
        "price": "1.00",
    }
    with pytest.raises(RhMcpLiveExitsDisabled):
        adapter.place_option_order(order)
    deny = json.loads(audit.read_text().strip().splitlines()[-1])
    assert deny["invariant"] == "I7"


def test_open_leg_allowed_when_live_entries_on(tmp_path, monkeypatch):
    monkeypatch.delenv("XSP_LANE_A_LIVE_ENTRIES", raising=False)
    monkeypatch.delenv("RH_AGENTIC_ACCOUNT_ID", raising=False)
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
    cfg = RhMcpConfig(
        token_path=token,
        agentic_account_id="agentic-1",
        live_entries=True,
        require_review_before_place=True,
    )
    adapter = RobinhoodMCPAdapter(
        config=cfg,
        http_post=lambda *a: {"result": {"structuredContent": {"ok": True}}},
    )
    out = adapter.buy_to_open(instrument_id="o1", limit_price=1.23, quantity=1)
    assert out["placed"] == {"ok": True}


def test_get_buying_power_takes_conservative_value(tmp_path):
    cfg = RhMcpConfig(agentic_account_id="agentic-1")
    adapter = RobinhoodMCPAdapter(config=cfg, http_post=lambda *a: {})
    adapter.call_tool = lambda name, args: {  # type: ignore[method-assign]
        "buying_power": "1200.00",
        "unleveraged_buying_power": "1000.00",
        "cash": "1000.00",
    }
    assert adapter.get_buying_power("agentic-1") == 1000.0


def test_select_entry_contract_picks_cheapest_near_atm(tmp_path):
    cfg = RhMcpConfig(agentic_account_id="agentic-1")
    adapter = RobinhoodMCPAdapter(config=cfg, http_post=lambda *a: {})
    routes = {
        "get_option_chains": {
            "symbol": "XSP",
            "expiration_dates": ["2026-07-21", "2026-08-21"],
        },
        "get_index_quotes": {"results": [{"last_trade_price": "755.0"}]},
        "get_option_instruments": {
            "results": [
                {"id": "inst-755", "strike_price": "755.0000", "type": "call"},
            ]
        },
        "get_option_quotes": {
            "results": [
                {
                    "instrument_id": "inst-750",
                    "ask_price": "1.05",
                    "bid_price": "0.95",
                    "mark_price": "1.00",
                },
                {
                    "instrument_id": "inst-755",
                    "ask_price": "0.80",
                    "bid_price": "0.70",
                    "mark_price": "0.75",
                },
                {
                    "instrument_id": "inst-760",
                    "ask_price": "0.60",
                    "bid_price": "0.50",
                    "mark_price": "0.55",
                },
            ]
        },
    }
    # Return all three strikes' instruments regardless of requested strike.
    instruments = [
        {"id": "inst-750", "strike_price": "750.0000", "type": "call"},
        {"id": "inst-755", "strike_price": "755.0000", "type": "call"},
        {"id": "inst-760", "strike_price": "760.0000", "type": "call"},
    ]

    def fake_call(name, args):
        if name == "get_option_instruments":
            return {"results": instruments}
        return routes[name]

    adapter.call_tool = fake_call  # type: ignore[method-assign]
    from datetime import date as _date

    chosen = adapter.select_entry_contract(today=_date(2026, 7, 1))
    assert chosen["instrument_id"] == "inst-755"  # nearest ATM, not cheapest OTM
    assert chosen["expiration_date"] == "2026-07-21"  # min DTE
    assert chosen["dte"] == 20


def test_cheapest_near_atm_prefers_nearest_strike_not_cheapest_otm(tmp_path):
    cfg = RhMcpConfig(agentic_account_id="agentic-1")
    adapter = RobinhoodMCPAdapter(config=cfg, http_post=lambda *a: {})
    instruments = [
        {"id": "inst-750", "strike_price": "750.0000", "type": "call"},
        {"id": "inst-755", "strike_price": "755.0000", "type": "call"},
        {"id": "inst-760", "strike_price": "760.0000", "type": "call"},
    ]

    def fake_call(name, args):
        if name == "get_option_chains":
            return {"symbol": "XSP", "expiration_dates": ["2026-07-21"]}
        if name == "get_index_quotes":
            return {"results": [{"last_trade_price": "755.0"}]}
        if name == "get_option_instruments":
            return {"results": instruments}
        if name == "get_option_quotes":
            return {
                "results": [
                    {
                        "instrument_id": "inst-750",
                        "ask_price": "1.05",
                        "bid_price": "0.95",
                        "mark_price": "1.00",
                    },
                    {
                        "instrument_id": "inst-755",
                        "ask_price": "0.80",
                        "bid_price": "0.70",
                        "mark_price": "0.75",
                    },
                    {
                        "instrument_id": "inst-760",
                        "ask_price": "0.60",
                        "bid_price": "0.50",
                        "mark_price": "0.55",
                    },
                ]
            }
        raise AssertionError(name)

    adapter.call_tool = fake_call  # type: ignore[method-assign]
    from datetime import date as _date

    chosen = adapter.select_entry_contract(
        strike_pick="cheapest_near_atm", today=_date(2026, 7, 1)
    )
    assert chosen["instrument_id"] == "inst-755"
    assert chosen["strike"] == 755.0


def test_select_entry_contract_picks_nearest_target_dte(tmp_path):
    cfg = RhMcpConfig(agentic_account_id="agentic-1")
    adapter = RobinhoodMCPAdapter(config=cfg, http_post=lambda *a: {})

    def fake_call(name, args):
        if name == "get_option_chains":
            return {
                "symbol": "XSP",
                "expiration_dates": ["2026-07-15", "2026-08-05", "2026-08-30"],
            }
        if name == "get_index_quotes":
            return {"results": [{"last_trade_price": "755.0"}]}
        if name == "get_option_instruments":
            return {
                "results": [
                    {
                        "id": f"inst-{args['expiration_dates']}",
                        "strike_price": args["strike_price"],
                        "type": "call",
                    }
                ]
            }
        if name == "get_option_quotes":
            return {
                "results": [
                    {
                        "instrument_id": iid,
                        "ask_price": "1.00",
                        "bid_price": "0.90",
                        "mark_price": "0.95",
                    }
                    for iid in args["instrument_ids"]
                ]
            }
        raise AssertionError(name)

    adapter.call_tool = fake_call  # type: ignore[method-assign]
    from datetime import date as _date

    chosen = adapter.select_entry_contract(
        dte_pick="target", dte_target=35, today=_date(2026, 7, 1)
    )
    assert chosen["expiration_date"] == "2026-08-05"
    assert chosen["dte"] == 35


def test_select_entry_contract_picks_otm_one_strike(tmp_path):
    cfg = RhMcpConfig(agentic_account_id="agentic-1")
    adapter = RobinhoodMCPAdapter(config=cfg, http_post=lambda *a: {})

    instruments = [
        {"id": "inst-750", "strike_price": "750.0000", "type": "call"},
        {"id": "inst-755", "strike_price": "755.0000", "type": "call"},
        {"id": "inst-760", "strike_price": "760.0000", "type": "call"},
    ]

    def fake_call(name, args):
        if name == "get_option_chains":
            return {"symbol": "XSP", "expiration_dates": ["2026-07-21"]}
        if name == "get_index_quotes":
            return {"results": [{"last_trade_price": "755.0"}]}
        if name == "get_option_instruments":
            return {"results": instruments}
        if name == "get_option_quotes":
            return {
                "results": [
                    {
                        "instrument_id": iid,
                        "ask_price": "1.00",
                        "bid_price": "0.90",
                        "mark_price": "0.95",
                    }
                    for iid in args["instrument_ids"]
                ]
            }
        raise AssertionError(name)

    adapter.call_tool = fake_call  # type: ignore[method-assign]
    from datetime import date as _date

    chosen = adapter.select_entry_contract(
        strike_pick="otm_one", atm_steps=1, today=_date(2026, 7, 1)
    )
    assert chosen["strike"] == 760.0
    assert chosen["instrument_id"] == "inst-760"


def test_select_entry_contract_raises_when_no_expiration(tmp_path):
    cfg = RhMcpConfig(agentic_account_id="agentic-1")
    adapter = RobinhoodMCPAdapter(config=cfg, http_post=lambda *a: {})
    adapter.call_tool = lambda name, args: {  # type: ignore[method-assign]
        "symbol": "XSP",
        "expiration_dates": ["2026-07-03"],  # 2 DTE, below window
    }
    from datetime import date as _date

    with pytest.raises(RhMcpError):
        adapter.select_entry_contract(today=_date(2026, 7, 1))
