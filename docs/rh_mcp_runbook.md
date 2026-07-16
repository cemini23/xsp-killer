# Robinhood Agentic MCP runbook (XSP Killer)

Paper mode stays default. This runbook covers **readiness → connect → live exits** when the operator is ready.

Canonical plan: `briefs/2026-06-29_xsp-robinhood-agentic-mcp-connection-cemini-prod.md`

## Operator split (read this first)

| Who | Doc | Host | Token path |
|-----|-----|------|------------|
| **Claudio** (cemini-prod) | [`rh_mcp_claudio.md`](rh_mcp_claudio.md) | Linux VPS `/opt/xsp-killer` | `${XDG_STATE_HOME:-~/.local/state}/xsp-killer/robinhood_mcp_token.json` |
| **David** (operator RH) | [`rh_mcp_david.md`](rh_mcp_david.md) | Windows | `%LOCALAPPDATA%\xsp-killer\robinhood_mcp_token.json` (**not** OneDrive) |

**Never** share Agentic account ids or OAuth tokens across operators. Each person authenticates **their** Robinhood Agentic account.

## Current posture (paper)

| Env | Default | Meaning |
|-----|---------|---------|
| `XSP_LANE_A_RH_POLL` | `false` | Legacy `robin_stocks` read poll |
| `XSP_LANE_A_RH_MCP` | `false` | Official Agentic MCP read adapter |
| `XSP_LANE_A_LIVE_ENTRIES` | `false` | Authorizes live buy-to-open (opens). Gates `place_option_order` legs with `position_effect=open` |
| `XSP_LANE_A_LIVE_EXITS` | `false` | Authorizes live sell-to-close (closes). Gates `place_option_order` legs with `position_effect=close` |

Reads require **either** `XSP_LANE_A_RH_MCP=true` (preferred) **or** `XSP_LANE_A_RH_POLL=true` (legacy). Writes always require MCP + the matching live flag: **opens** need `LIVE_ENTRIES`, **closes** need `LIVE_EXITS` (ambiguous effect defaults to exit-semantics). Opening and closing risk are gated independently on purpose.

## Phase 0 — Read-only MCP (operator + server)

1. Complete desktop OAuth (Robinhood Agentic Trading → MCP URL in Cursor).
2. Fill `config/rh_mcp_audit.md` — confirm options tools exist on your account.
3. Export token to `${XDG_STATE_HOME:-~/.local/state}/xsp-killer/robinhood_mcp_token.json` (mode `600`, service-user only).
4. Set `RH_AGENTIC_ACCOUNT_ID` in `.env` (Agentic account only).
5. Enable reads: `XSP_LANE_A_RH_MCP=true` (keep `XSP_LANE_A_RH_POLL=false`).
6. Health check:

```bash
cd /opt/xsp-killer
PYTHONPATH=. python3 scripts/rh_mcp_health.py
```

### VPS OAuth via Claude Code (headless prod)

Robinhood MCP is pre-registered on this box (`claude mcp list` → `robinhood-trading`).

1. From your **local machine**, SSH with port forward (OAuth callback listens on VPS `localhost:3118`):

```bash
ssh -L 3118:127.0.0.1:3118 YOUR_USER@YOUR_VPS
```

2. On the VPS, in an interactive session:

```bash
cd /opt/xsp-killer
claude
# then: /mcp → robinhood-trading → Authenticate
# open the printed URL in your local browser (tunnel forwards :3118)
```

3. After OAuth succeeds, sync token into xsp-killer:

```bash
cd /opt/xsp-killer
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/xsp-killer"
python3 scripts/rh_mcp_sync_claude_token.py \
  --out "${XDG_STATE_HOME:-$HOME/.local/state}/xsp-killer/robinhood_mcp_token.json"
```

4. Set Agentic account id + enable MCP reads in `.env`:

```bash
# RH_AGENTIC_ACCOUNT_ID=<from get_accounts in MCP audit>
# XSP_LANE_A_RH_MCP=true
```

5. Re-run `scripts/rh_mcp_health.py` — expect MCP positions read (or empty list).

**Cursor desktop alternative:** Settings → Tools & MCPs → add `https://agent.robinhood.com/mcp/trading`, authenticate, then export the token to the platform default above (same JSON shape as sync script output).

### Token migration and overrides

- Windows: move the token to
  `%LOCALAPPDATA%\xsp-killer\robinhood_mcp_token.json`.
- POSIX: move it to
  `${XDG_STATE_HOME:-~/.local/state}/xsp-killer/robinhood_mcp_token.json`.
- `RH_MCP_TOKEN_PATH` overrides YAML; a non-empty YAML `token_path` overrides
  the platform default.
- The adapter and health startup refuse paths resolving inside the repository
  or a OneDrive workspace. `XSP_RH_MCP_ALLOW_REPO_TOKEN_FOR_DEVELOPMENT=true`
  is only for explicit local development, never operations.

7. Compare MCP vs legacy poll (optional parallel week):

```bash
XSP_LANE_A_RH_MCP=true XSP_LANE_A_RH_POLL=true PYTHONPATH=. python3 scripts/rh_mcp_health.py --compare-legacy
```

8. Verify audit log: `logs/rh_mcp_audit.jsonl`

## Phase 1 — Review-only exit dry run

Lane A monitor calls `review_option_order` on exit signals when MCP is enabled, and (account empty) runs a review-only proof-of-life canary each run. **No** `place_option_order` while `XSP_LANE_A_LIVE_EXITS=false`.

Gate: paper soak ≥1 entered+closed trade post-epoch (current regime blocker).

Verified 2026-07-07: headless `place → cancel` works with no human approval (deep-OTM $0.01 order, unfilled, cancelled; see `config/rh_mcp_audit.md`).

## Phase 2 — Live exits (operator GO)

When `XSP_LANE_A_LIVE_EXITS=true` and the kill switch is clear, the monitor **auto-places** a sell-to-close on real exit alerts (`review → place`, limit at mark). Placement is idempotent per (option, trading day, exit reason) via a deterministic `ref_id`, so the 4 morning runs cannot duplicate an exit.

1. Fund **Agentic account only** (isolated from primary RH book).
2. Set `XSP_LANE_A_LIVE_EXITS=true` in `deploy/systemd/xsp-killer-lane-a-monitor.service` (currently `false`), reinstall units (`scripts/install_systemd.sh`), `daemon-reload`.
3. Confirm `RH_AGENTIC_ACCOUNT_ID`; single-contract test sell; confirm push notification.
4. Rollback drill: set `XSP_LANE_A_LIVE_EXITS=false` **and** disconnect agent in Robinhood app (≤60s stop).

## Phase 2 — Live entries (operator GO)

When `XSP_LANE_A_LIVE_ENTRIES=true` and the kill switch is clear, the entry cron **auto-places** a buy-to-open after all paper-entry gates pass. It selects the real XSP contract per the Lane A rules (`select_entry_contract`), checks account buying power, and **skips (fail-safe) rather than errors** if the contract costs more than available cash. Idempotent per (instrument, trading day) via a deterministic `ref_id`. Paper entry keeps running as a shadow record; exits act only on the resulting real broker position.

1. Fund the Agentic account (≥ one contract's cost; currently $1,000).
2. Set `XSP_LANE_A_LIVE_ENTRIES=true` in `deploy/systemd/xsp-killer-lane-a-entry.service` **and** `…-intraday.service` (currently `false`), reinstall units, `daemon-reload`.
3. Confirm one clean auto entry (`decision.live_order.placed=true`) then let the monitor auto-exit it next morning.
4. Rollback: set `XSP_LANE_A_LIVE_ENTRIES=false` (opens stop; any open position can still be closed via `LIVE_EXITS`).

## Kill switches

| Action | Effect |
|--------|--------|
| `XSP_LANE_A_KILL_SWITCH=true` | **Emergency halt** — blocks all `place_option_order` (I8) even if live exits on; cancels still allowed |
| `touch .local/KILL_SWITCH` (or `$XSP_LANE_A_KILL_FILE`) | Same as above via sentinel file — no restart needed |
| `XSP_LANE_A_LIVE_ENTRIES=false` | Adapter rejects buy-to-open (open) placements (I7) |
| `XSP_LANE_A_LIVE_EXITS=false` | Adapter rejects sell-to-close (close) placements (I7) |
| Robinhood app → disconnect agent | OAuth revoked; reads fail until re-auth |
| systemd stop timers | No cron evaluation |

## Do not

- Store an OAuth token anywhere inside a repository/synchronized workspace or paste it in chat
- Enable live exits before MCP tool audit + paper soak gates pass
- Route orders to non-Agentic accounts (adapter hard-rejects)
