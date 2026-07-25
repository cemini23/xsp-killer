# Plan — prod briefs → XSP Killer (2026-07-25)

**Status:** READY FOR GROK

**Sources scanned:** `/opt/cemini/briefs/*2026-07-2[4-5]*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH sleeve; no integral solvers; no strategy gate flips; **no aisuite adapter code** until spike approved.

## Route
- **Lane:** hard (log-only weather CODE, mirror K193)
- **Executor:** Grok (always-approve) → claude-ds → Cursor only if chain exhausted

## Brief triage

| Brief | Action |
|-------|--------|
| **K195** `xsp-2026-07-25_k195-aisuite-crude-teaser.md` (cemini, **new**) | CODE: log-only `k195` extras (mirror K193). Brief says "**No code** until adapter spike approved" → weather notes only; no aisuite client wiring. |
| K193 / K191 | Already shipped (`d73745d`) |
| `pm-2026-07-25_k195-lebron-omlx` | Skip — PM/Kalshi, not XSP |
| Harness K210–K219 | Skip — cemini agent harness, not XSP |

## Implement (safe CODE)

### 1) K195 log-only macro weather
Add `k195:` to `config/k155_operator_notes.yaml`:
- aisuite (andrewyng/aisuite MIT): Context / steal provider-uniform client shape for future signal-eval failovers — `no_stack_rewrite: true`, `no_adapter_until_spike_approved: true`
- CF macro positioning + crude risk teaser: title ≠ signal; confirm report before overnight size changes
- Continue prior caution stack (K193 FFJ / K191 treasury)
- `no_integral_solver: true` / `no_strategy_code: true`

Wire `load_k195_notes` + merge in `build_monitor_macro_weather_extras` (after k193).

### 2) Tests
Extend `tests/test_k155_macro_weather_notes.py` (load / includes / from_prod / run_monitor). Update overnight overwrite asserts if `lane_a_overnight` changes.

### 3) Hygiene
Lint + focused pytest + commit + push → CI green. No `LIVE_*`. Do not commit `_local/`, `logs/`, `.env`, handoffs unless useful.

## Done when
- `k195_version` in monitor extras offline
- Focused pytest + CI green on `origin/main`
