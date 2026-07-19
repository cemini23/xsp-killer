# Plan — prod briefs → XSP Killer (2026-07-19)

**Status:** READY FOR GROK

**Sources scanned:** `/opt/cemini/briefs/*2026-07-1[6-9]*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH AI sleeve; no integral solvers; no strategy gate flips from weather notes.

## Brief triage

| Brief | Action |
|-------|--------|
| **K174** `xsp-2026-07-19_k174-macro-cf-damaged-goods.md` (cemini, **new**) | CODE: log-only `k174` extras (mirror K173). Brief says "**No code**" → interpret as no sleeve/solver/LIVE/strategy changes; operator weather notes only. |
| K173 CF momentum unwind + carry | Already shipped (`49d99ba`) — K174 continues Jul 16–19 CF regime packet |
| K172 CF view shift + Asia AI | Already shipped (`f3f5b3c`) |
| K170 Korea/SOX/DXY | Already shipped |
| Debit-spread shadow soak / Stage B / Friday rules | Already shipped; ops soak continues — no new grid this pass |
| `pm-2026-07-19_k174-polymarket-5min-manipulation` | Skip — Polymarket, not XSP |
| K188–K189 / K179–K182 harness / policy | Skip — cemini agent harness, not XSP |

## Implement (safe CODE)

### 1) K174 log-only macro weather
Add `k174:` to `config/k155_operator_notes.yaml`:
- Macro Charts Jul 19 teaser: momentum crash / capitulation / flows / rates / oil / vol + sector long diversification — bounce R/R unclear → **do not chase**
- Treat CF Jul 16–19 as one regime packet (view changed → unwind/carry → weekend depth-of-field)
- Keep overnight Lane A criteria tight vs prior K172–K173 caution
- `no_integral_solver: true` / `no_strategy_code: true` (honors brief “No code” for trading path)

Wire `load_k174_notes` + merge in `build_monitor_macro_weather_extras` (mirror k173).

Tests in `tests/test_k155_macro_weather_notes.py` (load + merge + prod config + monitor attach).

Sync brief already at `briefs/xsp-2026-07-19_k174-macro-cf-damaged-goods.md`.

### 2) Hygiene
- Do **not** flip `LIVE_*`.
- After green: **ruff/lint + focused pytest + commit + push** so CI runs on `main`.
- Do not commit `briefs/_local/`, `logs/*`, `.env`, or secrets.

### 3) Running version (post-push verify)
Timers use `WorkingDirectory=/opt/xsp-killer` (pull≈deploy). After push:
1. Confirm `git rev-parse HEAD` matches intended K174 commit and tracks `origin/main`
2. Confirm systemd `XSP_LANE_A_LIVE_ENTRIES=false` / `LIVE_EXITS=false` (or env equivalents)
3. Smoke: `python3 -c` build_monitor_macro_weather_extras → `k174_version` present
4. Optional: `systemctl start xsp-killer-lane-a-monitor.service` once and journal-grep `k174` / macro_weather (fail-open OK)
5. Confirm GitHub Actions CI green on the push commit

## Done when
- Monitor extras expose `k174_version` + fields offline
- Focused pytest green
- Ruff/bandit/CI green on push
- Commit + push to `origin/main`

## Out of scope
- Enabling live RH writes / new AI sleeve
- Expanding BS-lite Stage B grids
- Debit-spread live wiring / historical fills
- cemini harness / Polymarket K174 work
- Integral solvers
