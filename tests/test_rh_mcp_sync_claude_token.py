"""Tests for safe Robinhood MCP token synchronization."""

from __future__ import annotations

import json

import pytest

import scripts.rh_mcp_sync_claude_token as sync
import xsp_killer.robinhood_mcp as robinhood_mcp
from xsp_killer.robinhood_mcp import RhMcpNotReady


def _credentials(path):
    path.write_text(
        json.dumps(
            {
                "mcpOAuth": {
                    "entry": {
                        "serverUrl": "https://agent.robinhood.com/mcp/trading",
                        "accessToken": "test-placeholder",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_sync_default_output_calls_shared_default_token_path(monkeypatch, tmp_path):
    credentials = _credentials(tmp_path / "credentials.json")
    expected = tmp_path / "state/token.json"
    stale_default = tmp_path / "repo-local/token.json"
    monkeypatch.setattr(sync, "default_token_path", lambda: expected, raising=False)
    monkeypatch.setattr(
        sync,
        "DEFAULT_TOKEN_PATH",
        stale_default,
        raising=False,
    )
    monkeypatch.setattr(sync, "validate_token_path", lambda path: path, raising=False)

    assert sync.main(["--claude-creds", str(credentials)]) == 0
    assert expected.is_file()
    assert not stale_default.exists()


def test_sync_rejects_explicit_output_under_repository(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    credentials = _credentials(tmp_path / "credentials.json")
    monkeypatch.setattr(robinhood_mcp, "ROOT", repo)
    monkeypatch.delenv(
        "XSP_RH_MCP_ALLOW_REPO_TOKEN_FOR_DEVELOPMENT",
        raising=False,
    )

    with pytest.raises(RhMcpNotReady, match="development override"):
        sync.main(
            [
                "--claude-creds",
                str(credentials),
                "--out",
                str(repo / "token.json"),
            ]
        )
