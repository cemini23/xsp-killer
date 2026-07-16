# Plan — prod briefs → XSP Killer (2026-07-16 AM)

**Sources scanned:** `/opt/cemini/briefs/xsp-*` + recent `2026-07-1*.md`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no SDF/Dupire solvers; no Turbovec prod index; no new RH sleeve.

## Brief triage

| Brief | Action |
|-------|--------|
| **K170** `xsp-2026-07-16_k170-macro-korea-sox-reindustrialization.md` (cemini, **new**) | CODE: log-only `k170` extras (same pattern as K167) |
| K170 PM/HL sim-markets / CXMT | Skip — not XSP; brief says no code |
| K167 / K168 / K161 / K162 / mentor mid-tenor / v9 CODE / UW backtest / Nagus sensor | Already shipped (`d970a0d`…`d06d68a`) |
| David onsite / UW key / OneDrive token | Ops only — out of scope |

## Implement (safe CODE)

### 1) K170 log-only macro weather
Add `k170:` to `config/k155_operator_notes.yaml`:
- Korea levered-ETF clamp / Memory late-Q3 risk — overnight conditional on SOX ~12k support + no Korea liquidity cascade
- SOX ~$12k support watch
- DXY May-uptrend / ~100.50 break test — tighten overnight until close confirms
- US re-industrialization / defense = regime context only (`no_new_rh_sleeve: true`)
- Theory shelf SDF/Dupire = REFERENCE only (`no_integral_solver: true`)
- Turbovec = optional local experiment (`no_prod_index_swap: true`)

Wire `load_k170_notes` + merge in `build_monitor_macro_weather_extras` (mirror k167).

Tests in `tests/test_k155_macro_weather_notes.py`.

Copy/sync brief under `briefs/xsp-2026-07-16_k170-macro-korea-sox-reindustrialization.md`.

### 2) Hygiene (same pass)
- Include uncommitted Nagus alignment edit on `briefs/2026-07-16_uw-lane-a-backtest-plan.md` if still dirty.
- Update `briefs/2026-07-15_v9-backlog-postpatch-status.md` with a K170 Done row under prod-briefs.

## Done when
- Monitor extras expose `k170_version` + fields offline.
- Focused pytest green.
- Local commit (no push unless asked). No `LIVE_*`.

## Out of scope
- UW key install, David OAuth, GitHub invite.
- Implementing Turbovec / SDF / Dupire / Inkling.
- Enabling live RH writes.
