# Robinhood Agentic MCP — Claudio (cemini-prod VPS)

**Audience:** Claudio / cemini-prod at `/opt/xsp-killer` on Hetzner.  
**Do not** hand this token or `RH_AGENTIC_ACCOUNT_ID` to David’s Windows setup.

Canonical phases: [`rh_mcp_runbook.md`](rh_mcp_runbook.md).  
David Windows path: [`rh_mcp_david.md`](rh_mcp_david.md).

## Paths (Linux VPS)

| Item | Path |
|------|------|
| Repo | `/opt/xsp-killer` |
| OAuth token | `${XDG_STATE_HOME:-~/.local/state}/xsp-killer/robinhood_mcp_token.json` (mode `600`) |
| Kill switch | `/opt/xsp-killer/.local/KILL_SWITCH` or env |
| Systemd units | `deploy/systemd/xsp-killer-lane-a-*.service` |
| Timers | entry / intraday / monitor under `deploy/systemd/` |

## Phase 0 — Read-only (prod)

1. Desktop OAuth or Claude Code tunnel (`ssh -L 3118:…` → `/mcp` → sync):

```bash
cd /opt/xsp-killer
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/xsp-killer"
python3 scripts/rh_mcp_sync_claude_token.py \
  --out "${XDG_STATE_HOME:-$HOME/.local/state}/xsp-killer/robinhood_mcp_token.json"
```

2. Set `RH_AGENTIC_ACCOUNT_ID` (Claudio Agentic only) and `XSP_LANE_A_RH_MCP=true` in `.env` / unit Environment.
3. Keep `XSP_LANE_A_LIVE_ENTRIES=false` / `XSP_LANE_A_LIVE_EXITS=false`.
4. Health:

```bash
cd /opt/xsp-killer
PYTHONPATH=. python3 scripts/rh_mcp_health.py
```

5. Paper soak continues via systemd timers; scoreboard at `briefs/xsp-lane-a-variants-scoreboard.json`.

## Ops vs David

| Concern | Claudio (this doc) | David |
|---------|--------------------|--------|
| Host | Hetzner VPS Linux | Windows desktop |
| Token | XDG state directory | `%LOCALAPPDATA%\xsp-killer\` |
| Account pin | Claudio Agentic | David Agentic (separate) |
| Paper soak | **Primary** (timers) | Optional local / prefer VPS evidence |
| Live writes | NO-GO until operator GO | NO-GO |

## Migration from the repository

Before health or adapter startup, move any existing token to the service
user's state directory:

```bash
install -d -m 700 "${XDG_STATE_HOME:-$HOME/.local/state}/xsp-killer"
mv /opt/xsp-killer/.local/robinhood_mcp_token.json \
  "${XDG_STATE_HOME:-$HOME/.local/state}/xsp-killer/robinhood_mcp_token.json"
chmod 600 "${XDG_STATE_HOME:-$HOME/.local/state}/xsp-killer/robinhood_mcp_token.json"
```

The service and migration command must run as the same user. Do not set
`XSP_RH_MCP_ALLOW_REPO_TOKEN_FOR_DEVELOPMENT` on the VPS.

## Install / reinstall units

```bash
cd /opt/xsp-killer
sudo bash scripts/install_systemd.sh
sudo systemctl daemon-reload
```

## K168 watch — Bonsai / Undici (no RH order path)

Bonsai-demo (local ternary / low-bit LLM) and Undici (Node HTTP dispatcher/pooling) are **eval and future REST hedges only**. Do **not** install them as a dependency of Robinhood order placement, grant/review, or `LIVE_*` place paths. Optional offline brief/sentiment eval is out of band; pin/soak any REST client swap before global use. **No live RH code from K168.**
