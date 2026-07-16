#!/usr/bin/env python3
"""Copy Robinhood MCP OAuth token from Claude Code credentials to xsp-killer."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xsp_killer.robinhood_mcp import (  # noqa: E402
    default_token_path,
    validate_token_path,
)

DEFAULT_CLAUDE_CREDS = Path.home() / ".claude" / ".credentials.json"


def _load_claude_robinhood_entry(creds_path: Path) -> dict:
    if not creds_path.is_file():
        raise SystemExit(f"Claude credentials missing: {creds_path}")
    data = json.loads(creds_path.read_text(encoding="utf-8"))
    oauth = data.get("mcpOAuth") or {}
    for entry in oauth.values():
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("serverUrl") or "")
        if "agent.robinhood.com/mcp/trading" in url:
            return entry
    raise SystemExit(
        "No robinhood-trading entry in Claude mcpOAuth — run /mcp auth first"
    )


def _token_payload(entry: dict) -> dict:
    access = str(entry.get("accessToken") or entry.get("access_token") or "").strip()
    if not access:
        raise SystemExit(
            "Robinhood MCP accessToken empty — complete OAuth in `claude` → /mcp first"
        )
    payload: dict = {"access_token": access}
    refresh = entry.get("refreshToken") or entry.get("refresh_token")
    if isinstance(refresh, str) and refresh.strip():
        payload["refresh_token"] = refresh.strip()
    for key in ("expiresAt", "expires_at", "sub", "user_id"):
        if entry.get(key) is not None:
            payload[key] = entry[key]
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claude-creds",
        type=Path,
        default=DEFAULT_CLAUDE_CREDS,
        help="Claude Code credentials JSON (default: ~/.claude/.credentials.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="token path (default: platform-local xsp-killer state directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate token present without writing",
    )
    args = parser.parse_args(argv)
    output_path = validate_token_path(args.out or default_token_path())

    entry = _load_claude_robinhood_entry(args.claude_creds)
    payload = _token_payload(entry)

    if args.dry_run:
        print("ok token present in Claude credentials")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(output_path, 0o600)
    print(f"wrote {output_path} (mode 600)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
