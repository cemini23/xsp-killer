# 2026-07-15 — v9 backlog status after post-merge patch (Claudio)

**Refs:** synthesis `briefs/2026-07-15_xsp-killer-super-audit-synthesis-v9.md` · merge `eeffa7f` · follow-up commit on this note.

## Already patched in David's PR (`41925a0` / `eb6ed88`)

| P0 | Item | Status |
|----|------|--------|
| 2 | Reject unknown `position_effect` | **Done** |
| 3 | Validate review business outcome before place grant | **Done** |
| 4 | Always evaluate paper + RH books | **Done** |
| 5 | Zero-mark preserve + expired full-debit | **Done** (+ tests) |
| 7 | Live `cheapest_near_atm` match paper | **Done** |
| — | Human dual-ack `LIVE_VARIANT_ID` | **Done** (`live_gates.py`) |
| — | Portable `fs_lock` (fcntl optional) | **Done** (portalocker / fcntl / msvcrt — v9 CODE) |

## Patched this session (remaining code gaps)

| Item | Change |
|------|--------|
| P0 #1 fan-out | Non-promoted **variant monitors skip MCP entirely** when `LIVE_VARIANT_ID` is set and mismatched (no review/grant spam) |
| P1 #9 unfilled GFD | Exit `ref_id` now AM/PM session-keyed so afternoon can retry an unfilled morning stop |
| P1 #10 grant TIF | `_review_grant_key` includes `time_in_force` |
| P1 #12 pin∈token | `pinned_account_on_token()` + `rh_mcp_health.py` warning |
| P0 #8 VPS evidence | Scoreboard rebuilt on prod (`briefs/xsp-lane-a-variants-scoreboard.json` updated) |

## CODE backlog closed (v9 remaining plan — 2026-07-15)

| # | Item | Status | Notes |
|---|------|--------|-------|
| P1 #11 | Portable locks | **Done** | `fs_lock.py`: portalocker → fcntl → msvcrt; `portalocker` in `requirements.txt`; `tests/test_fs_lock.py` |
| P1 #13 | GTH bid + wide-spread veto | **Done** | Bid limit outside RTH; TP veto when `(ask-bid)/ask > 0.25`; SL may fire at bid; paper marks store bid/ask |
| P1 #14 | `conductor_shadow` vs DIP_BOUNCE | **Done** | `conductor_shadow_skip_count` / `dip_bounce_sessions` in telemetry + scoreboard rows |
| P2 #15 | Clones + one 50–55 DTE | **Done** | `promotion_summary` collapses confounded families; **`v2_dip_swing_55dte_otm` active**; 45/50/60 false |
| P2 #16 | David vs Claudio docs | **Done** | `docs/rh_mcp_david.md`, `docs/rh_mcp_claudio.md`, runbook pointer; diagnosis refreshed |
| P2 #17 | Fusion runner empty content | **Done** | Multipart extract + retry without plugins/tools; clear `finish_reason` error |

## Still open — route / tomorrow at David's (ops, not code)

| # | Item | Owner tomorrow |
|---|------|----------------|
| P0 #6 | OAuth token **off OneDrive** → `%LOCALAPPDATA%\xsp-killer\` (or similar) | David |
| — | Install shared `UNUSUAL_WHALES_API_KEY` on Hetzner `/opt/tipdrop-scanner/.env` | David / Claudio |
| — | Accept GitHub write invite on `cemini23/xsp-killer` (stop forking) | David |
| — | RH Agentic OAuth on **David's** account; `rh_mcp_health.py` until pin check green | David |
| — | Keep `LIVE_ENTRIES=false` / `LIVE_EXITS=false` | Both |

## Verdict (unchanged)

**NO-GO live RH writes.** Paper soak on VPS **GO**. David path tomorrow: **reads-only** after token path + pin check, then stop.
