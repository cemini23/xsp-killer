"""Hard human variant review gate before live RH placement."""

from __future__ import annotations

import json

from xsp_killer.live_gates import (
    REQUIRED_STATEMENT,
    human_variant_review_allows,
)


def test_human_review_fails_closed_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("XSP_LANE_A_LIVE_VARIANT_ID", raising=False)
    monkeypatch.delenv("XSP_LANE_A_LIVE_HUMAN_ACK", raising=False)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(tmp_path / "missing.json"))
    ok, reason = human_variant_review_allows("v2_dip_swing_14dte")
    assert ok is False
    assert "LIVE_VARIANT_ID unset" in reason


def test_human_review_requires_dual_env_and_file(monkeypatch, tmp_path):
    vid = "v2_dip_swing_14dte"
    ack = tmp_path / "LIVE_HUMAN_REVIEW.json"
    ack.write_text(
        json.dumps({"variant_id": vid, "statement": REQUIRED_STATEMENT}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", vid)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK", vid)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(ack))
    ok, reason = human_variant_review_allows(vid)
    assert ok is True
    assert reason == "human variant review ok"


def test_human_review_rejects_env_mismatch(monkeypatch, tmp_path):
    vid = "v2_dip_swing_14dte"
    ack = tmp_path / "LIVE_HUMAN_REVIEW.json"
    ack.write_text(
        json.dumps({"variant_id": vid, "statement": REQUIRED_STATEMENT}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", vid)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK", "wrong_variant")
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(ack))
    ok, reason = human_variant_review_allows(vid)
    assert ok is False
    assert "HUMAN_ACK" in reason


def test_human_review_rejects_wrong_statement(monkeypatch, tmp_path):
    vid = "v2_dip_swing_14dte"
    ack = tmp_path / "LIVE_HUMAN_REVIEW.json"
    ack.write_text(
        json.dumps({"variant_id": vid, "statement": "looks good"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XSP_LANE_A_LIVE_VARIANT_ID", vid)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK", vid)
    monkeypatch.setenv("XSP_LANE_A_LIVE_HUMAN_ACK_PATH", str(ack))
    ok, reason = human_variant_review_allows(vid)
    assert ok is False
    assert "statement" in reason
