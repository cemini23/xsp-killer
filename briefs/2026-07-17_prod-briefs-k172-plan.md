# Plan — prod briefs → XSP Killer (2026-07-17)

**Status:** DONE

**Sources scanned:** `/opt/cemini/briefs/*2026-07-17*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH AI sleeve; no integral solvers; no strategy gate flips from weather notes.

## Brief triage

| Brief | Action |
|-------|--------|
| **K172** `xsp-2026-07-17_k172-capital-flows-view-shift.md` (cemini, **new**) | CODE: log-only `k172` extras (mirror K170). Brief says "**No code**" → interpret as no sleeve/solver/LIVE/strategy changes; operator weather notes only. |
| K179–K182 / K184–K187 harness / policy / ACP | Skip — Cemini agent harness, not XSP |
| K158 play-adequacy world-model | Skip — harness eval, not XSP |
| `pm-2026-07-17_k172-kalshi-teleprompter…` | Skip — Kalshi / PM, not XSP |
| K170 / entry-time / debit-spread Stage B | Already local (`f1db272`…) |

## Implement (safe CODE)

### 1) K172 log-only macro weather
Add `k172:` to `config/k155_operator_notes.yaml`:
- CF view shift / momentum unwind / carry risks — tighten Lane A overnight caution (context only)
- Asia AI selloff (Taiex/TSM / Kioxia / Korea margin-call chatter) — **do not chase** Memory/semis overnight; wait clear bounce R/R
- Keep Lane A tight vs existing K170 SOX/DXY gates + CF caution
- AI commoditization / cheap-open-model narrative = regime context (`no_new_rh_sleeve: true`)
- `no_integral_solver: true` / `no_strategy_code: true` (honors brief “No code” for trading path)

Wire `load_k172_notes` + merge in `build_monitor_macro_weather_extras` (mirror k170).

Tests in `tests/test_k155_macro_weather_notes.py` (load + merge + monitor attach).

Sync brief → `briefs/xsp-2026-07-17_k172-capital-flows-view-shift.md`.

### 2) Hygiene
- Include uncommitted tipdrop default fix on `scripts/optimize_entry_time.py` if still dirty (Hetzner `/opt/tipdrop-scanner` first).
- Do **not** push. Do **not** flip `LIVE_*`.

### 3) Running version (post-commit verify)
Timers use `WorkingDirectory=/opt/xsp-killer` (pull≈deploy). After local commit:
1. Confirm `git rev-parse HEAD` matches intended K172 commit
2. Confirm systemd `XSP_LANE_A_LIVE_ENTRIES=false` / `LIVE_EXITS=false`
3. Smoke: `python3 -c` build_monitor_macro_weather_extras → `k172_version` present
4. Optional: `systemctl start xsp-killer-lane-a-monitor.service` once and journal-grep `k172` / macro_weather (fail-open OK)

## Done when
- Monitor extras expose `k172_version` + fields offline
- Focused pytest green
- Local commit (no push)
- Deploy smoke confirms HEAD + LIVE_* false + k172 in extras

## Out of scope
- Enabling live RH writes / new AI sleeve
- Debit-spread live wiring / historical fills
- Cemini K179–K187 harness work
