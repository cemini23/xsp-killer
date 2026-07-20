# Plan — prod briefs → XSP Killer (2026-07-20)

**Status:** READY FOR GROK

**Sources scanned:** `/opt/cemini/briefs/*2026-07-1[9-9]*` + `*2026-07-20*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH AI sleeve; no integral solvers; no strategy gate flips from weather notes.

## Brief triage

| Brief | Action |
|-------|--------|
| **K177** `xsp-2026-07-20_k177-macro-damaged-goods-moontower-mixologist.md` (cemini, **new**) | CODE: log-only `k177` extras (mirror K174). Brief says "**No code**" → interpret as no sleeve/solver/LIVE/strategy changes; operator weather notes only. |
| K174 Macro damaged goods + CF weekend depth | Already shipped (`f2bbd1a`) — K177 is paid DAMAGED GOODS + Moontower mixologist follow-on |
| K173 / K172 / K170 | Already shipped |
| Debit-spread shadow soak / Stage B / Friday rules | Already shipped; ops soak continues — no new grid this pass |
| `pm-2026-07-20_k177-underdog-exchange-kalshi-wc` | Skip — Kalshi / PM, not XSP |
| K190–K196 harness / policy / CTI | Skip — cemini agent harness, not XSP |

## Implement (safe CODE)

### 1) K177 log-only macro weather
Add `k177:` to `config/k155_operator_notes.yaml`:
- Paid Macro Charts DAMAGED GOODS (Jul 19): momentum crash / **incomplete** capitulation — do not chase bounce until R/R clear
- VIX may have bottomed — treat **VIX >20 sustain** as vol-regime caution for overnight Lane A size (log-only; no size gate flip)
- Large AM VIX short + SOX coil ~12k = regime context (extends K170 SOX watch)
- Moontower mixologist: screen verticals / structure via **IV percentile × skew geometry** (straddle / RR / strangle collapse), not cocktail names / directional vibes
- `no_integral_solver: true` / `no_strategy_code: true` (honors brief “No code” for trading path)

Wire `load_k177_notes` + merge in `build_monitor_macro_weather_extras` (mirror k174).

Tests in `tests/test_k155_macro_weather_notes.py` (load + merge + prod config + monitor attach).

Sync brief → `briefs/xsp-2026-07-20_k177-macro-damaged-goods-moontower-mixologist.md`.

### 2) Hygiene
- Do **not** flip `LIVE_*`.
- After green: **ruff/lint + focused pytest + commit + push** so CI runs on `main`.
- Do not commit `briefs/_local/`, `briefs/handoffs/` (unless useful), `logs/*`, `.env`, or secrets.

### 3) Running version (post-push verify)
Timers use `WorkingDirectory=/opt/xsp-killer` (pull≈deploy). After push:
1. Confirm `git rev-parse HEAD` matches intended K177 commit and tracks `origin/main`
2. Confirm systemd `XSP_LANE_A_LIVE_ENTRIES=false` / `LIVE_EXITS=false` (or env equivalents)
3. Smoke: `python3 -c` build_monitor_macro_weather_extras → `k177_version` present
4. Optional: `systemctl start xsp-killer-lane-a-monitor.service` once and journal-grep `k177` / macro_weather (fail-open OK)
5. Confirm GitHub Actions CI green on the push commit; fix calendar flakes if CI fails unrelated tests

## Done when
- Monitor extras expose `k177_version` + fields offline
- Focused pytest green
- Ruff/bandit/CI green on push
- Commit + push to `origin/main`

## Out of scope
- Enabling live RH writes / new AI sleeve
- Auto size cuts from VIX>20 (notes only — no strategy gate)
- Expanding BS-lite Stage B grids / debit-spread live wiring
- cemini harness K190–K196 / Kalshi PM K177
- Integral solvers
