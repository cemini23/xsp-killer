# Plan — prod briefs → XSP Killer (2026-07-18)

**Status:** DONE

**Sources scanned:** `/opt/cemini/briefs/*2026-07-1[5-8]*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH AI sleeve; no integral solvers; no strategy gate flips from weather notes.

## Brief triage

| Brief | Action |
|-------|--------|
| **K173** `xsp-2026-07-18_k173-capital-flows-momentum-unwind.md` (cemini, **new**) | CODE: log-only `k173` extras (mirror K172). Brief says "**No code**" → interpret as no sleeve/solver/LIVE/strategy changes; operator weather notes only. |
| K172 CF view shift + Asia AI | Already shipped (`f3f5b3c`) — K173 is the paid follow-on risk map |
| K188–K189 / K179–K182 harness / policy | Skip — cemini agent harness, not XSP |
| `pm-2026-07-18_k173-flight-markets-airllm` | Skip — Kalshi / PM, not XSP |
| Debit-spread shadow soak / Stage B / Friday rules / spread×window | Already shipped (`75840ea`…`8ebccc7`); ops soak continues — no new grid this pass |

## Implement (safe CODE)

### 1) K173 log-only macro weather
Add `k173:` to `config/k155_operator_notes.yaml`:
- CF Jul 16–17 as one regime packet — view already changed; unwind/carry is the **risk map**
- Prefer wait for clear bounce R/R over momentum chase (extends K172 caution)
- Tavi Costa Macro Charts podcast teaser = Context only (no actionable free levels)
- Klement failure-gap = useful overconfidence check for ship gates / canary confidence — Context
- `no_integral_solver: true` / `no_strategy_code: true` (honors brief “No code” for trading path)

Wire `load_k173_notes` + merge in `build_monitor_macro_weather_extras` (mirror k172).

Tests in `tests/test_k155_macro_weather_notes.py` (load + merge + prod config + monitor attach).

Sync brief → `briefs/xsp-2026-07-18_k173-capital-flows-momentum-unwind.md`.

### 2) Hygiene
- Do **not** flip `LIVE_*`.
- After green: lint + commit + **push** so CI runs on `main`.

### 3) Running version (post-push verify)
Timers use `WorkingDirectory=/opt/xsp-killer` (pull≈deploy). After push:
1. Confirm `git rev-parse HEAD` matches intended K173 commit and tracks `origin/main`
2. Confirm systemd `XSP_LANE_A_LIVE_ENTRIES=false` / `LIVE_EXITS=false`
3. Smoke: `python3 -c` build_monitor_macro_weather_extras → `k173_version` present
4. Optional: `systemctl start xsp-killer-lane-a-monitor.service` once and journal-grep `k173` / macro_weather (fail-open OK)

## Done when
- Monitor extras expose `k173_version` + fields offline
- Focused pytest green
- Ruff/bandit/CI green on push
- Commit + push to `origin/main`

## Out of scope
- Enabling live RH writes / new AI sleeve
- Expanding BS-lite Stage B grids (prior search still RESEARCH ONLY)
- Debit-spread live wiring / historical fills
- Cemini K188–K189 harness work
