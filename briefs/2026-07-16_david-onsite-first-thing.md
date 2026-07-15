# 2026-07-16 — First thing at David's (XSP + UW)

**Paste this into Cursor Agent on David's PC after SSH/xsp kit is open.**

## Goal

Unblock shared UW on Hetzner paper + David RH **reads-only**; do **not** enable live place.

## Checklist

1. **GitHub:** Accept write invite on `cemini23/xsp-killer` if still pending. `git remote -v` on Desktop clone should push to `cemini23/xsp-killer` (not only the fork).
2. **UW key on prod (shared TipDrop Advanced):**
   ```bash
   ssh cemini-prod
   # follow /opt/tipdrop-scanner/INSTALL-UW-KEY-HETZNER.md
   # type UNUSUAL_WHALES_API_KEY into /opt/tipdrop-scanner/.env (chmod 600)
   systemctl start xsp-killer-lane-a-monitor.service
   ```
3. **RH token path:** Move OAuth token out of OneDrive into e.g. `%LOCALAPPDATA%\xsp-killer\robinhood_mcp_token.json`. Point `config/rh_mcp.yaml` / env `token_path` there. **David's** pin only.
4. **Health:** `python scripts/rh_mcp_health.py` — require `pinned_account_on_token: True`. If False → stop (wrong account).
5. **Flags stay false:** `XSP_LANE_A_LIVE_ENTRIES` / `XSP_LANE_A_LIVE_EXITS` unset/false.
6. **Pull prod brief:** `briefs/2026-07-15_v9-backlog-postpatch-status.md` — remaining P1/P2 only.

## Done when

- [ ] Hetzner monitor_eval can show non-null `uw_shadow` (or logged UW provider hit)
- [ ] David health: token path local + pin match
- [ ] No LIVE_* flipped
