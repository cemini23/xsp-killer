# Robinhood Agentic MCP — David (Windows operator)

**Audience:** David’s Robinhood Agentic account only.  
**Do not** reuse Claudio/cemini-prod token, pin, or account id.

Canonical phases and kill switches: [`rh_mcp_runbook.md`](rh_mcp_runbook.md).  
Claudio VPS path: [`rh_mcp_claudio.md`](rh_mcp_claudio.md).

## Paths (Windows)

| Item | Path |
|------|------|
| Repo (if local clone) | e.g. `C:\Users\<you>\…\xsp-killer` — **not** under OneDrive if avoidable |
| OAuth token (required) | `%LOCALAPPDATA%\xsp-killer\robinhood_mcp_token.json` |
| Kill switch file | `%LOCALAPPDATA%\xsp-killer\KILL_SWITCH` |
| Env / config | Local `.env` next to the runtime you use; never commit |

**Never** store the token under OneDrive-synced folders (including Desktop clones under OneDrive). That was a v9 P0 ops finding.

## Setup checklist (reads only)

1. Open **David’s** Robinhood Agentic account (not Claudio’s).
2. Desktop OAuth to `https://agent.robinhood.com/mcp/trading` (Cursor Tools & MCPs or Claude tunnel).
3. Export token JSON (`access_token`) to `%LOCALAPPDATA%\xsp-killer\robinhood_mcp_token.json` (restrict ACLs).
4. Set in local env:
   - `RH_AGENTIC_ACCOUNT_ID` = **David’s** Agentic account number from `get_accounts`
   - token path override if config still points at `.local/` (prefer absolute LOCALAPPDATA path)
   - `XSP_LANE_A_RH_MCP=true`
5. **Keep** `XSP_LANE_A_LIVE_ENTRIES=false` and `XSP_LANE_A_LIVE_EXITS=false`.
6. Health:

```bat
cd /d path\to\xsp-killer
set PYTHONPATH=.
python scripts\rh_mcp_health.py
```

Expect HIGH confidence and pin ∈ accounts for **this** token. Stop after green health — **no placement**.

## Runtime note

Production soak and file locks run on the **Linux VPS** (`/opt/xsp-killer`). Native Windows can run health + read-only scripts; full monitor/variant stack prefers VPS or WSL. Portable locks (`portalocker`) land in v9 CODE so Windows import no longer hard-depends on `fcntl`.

## Live writes

**NO-GO** until dual-ack `LIVE_VARIANT_ID`, fan-out gates, and operator GO. See runbook Phase 2 — do not flip live flags on David’s machine without that checklist.
