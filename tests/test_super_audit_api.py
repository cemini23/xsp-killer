"""Unit tests for super-audit API content extraction (v9 P2 #17)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_xsp_killer_super_audit_api.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_xsp_killer_super_audit_api", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_message_content_string():
    mod = _load_runner()
    assert mod._extract_message_content({"content": "  hello  "}) == "hello"


def test_extract_message_content_multipart_list():
    mod = _load_runner()
    msg = {
        "content": [
            {"type": "text", "text": "Part A"},
            {"type": "text", "text": "Part B"},
        ]
    }
    assert "Part A" in mod._extract_message_content(msg)
    assert "Part B" in mod._extract_message_content(msg)


def test_extract_message_content_null_returns_empty():
    mod = _load_runner()
    assert mod._extract_message_content({"content": None, "tool_calls": [{}]}) == ""
    assert mod._extract_message_content(None) == ""


def test_strip_fusion_plugins():
    mod = _load_runner()
    extra = {
        "plugins": [{"id": "fusion"}],
        "tools": [],
        "reasoning": {"effort": "high"},
    }
    cleaned = mod._strip_fusion_plugins(extra)
    assert cleaned is not None
    assert "plugins" not in cleaned
    assert "tools" not in cleaned
    assert cleaned.get("reasoning") == {"effort": "high"}


def test_call_retries_without_plugins_on_empty_tool_budget(monkeypatch):
    mod = _load_runner()
    calls: list[dict] = []

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json or {})
        if len(calls) == 1:
            return FakeResp(
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": None,
                                "tool_calls": [{"id": "1", "type": "function"}],
                            },
                        }
                    ],
                    "usage": {"completion_tokens": 24000},
                }
            )
        return FakeResp(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "# AUDIT\n\nOK"},
                    }
                ],
                "usage": {"completion_tokens": 100},
            }
        )

    import types
    import sys

    fake_httpx = types.SimpleNamespace(post=fake_post)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    text = mod._call_openai_compat(
        base_url="https://example.test/v1",
        api_key="k",
        model="openrouter/fusion",
        prompt="short",
        extra={"plugins": [{"id": "fusion"}]},
        max_tokens=100,
    )
    assert text.startswith("# AUDIT")
    assert len(calls) == 2
    assert "plugins" in calls[0]
    assert "plugins" not in calls[1]


def test_call_raises_clear_error_when_still_empty(monkeypatch):
    mod = _load_runner()

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": None, "tool_calls": [{"id": "x"}]},
                    }
                ],
                "usage": {"completion_tokens": 99},
            }

    import types
    import sys

    monkeypatch.setitem(
        sys.modules, "httpx", types.SimpleNamespace(post=lambda *a, **k: FakeResp())
    )

    with pytest.raises(RuntimeError, match="finish_reason"):
        mod._call_openai_compat(
            base_url="https://example.test/v1",
            api_key="k",
            model="openrouter/fusion",
            prompt="x",
            extra={"plugins": [{"id": "fusion"}]},
            max_tokens=50,
            _retried=True,
        )
