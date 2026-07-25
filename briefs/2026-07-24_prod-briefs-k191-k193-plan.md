# Plan — prod briefs → XSP Killer (2026-07-24)

**Status:** READY FOR GROK

**Sources scanned:** `/opt/cemini/briefs/*2026-07-2[2-4]*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH sleeve; no integral solvers; no strategy gate flips from weather notes; no auto-trust LLM news triage without FP budget.

## Route
- **Lane:** hard (log-only weather CODE, mirror K182)
- **Executor:** Grok (always-approve) → claude-ds → Cursor only if chain exhausted

## Brief triage

| Brief | Action |
|-------|--------|
| **K193** `xsp-2026-07-24_k193-ffj-newsflow-spx-selling.md` (cemini, **new**) | CODE: log-only `k193` extras (mirror K182). Brief says "**No code**" → weather notes only. |
| **K191** `xsp-2026-07-23_k191-treasury-compress-robinhood-chain.md` (cemini, **new**) | CODE: log-only `k191` extras (mirror K182). Brief says "**No code**" → weather notes only. |
| K182 illiquid IV / HF fragile | Already shipped (`d3e6841`) |
| `pm-2026-07-24_k193-*`, `pm-2026-07-23_k191-*` | Skip — PM/Kalshi, not XSP |
| Harness K206–K219 / K210–K214 | Skip — cemini agent harness, not XSP |

## Implement (safe CODE)

### 1) K191 log-only macro weather
Add `k191:` to `config/k155_operator_notes.yaml`:
- CF Treasury compression teaser = vol/regime watch only — no Lane A size on free teaser
- Robinhood Chain (Arbitrum L2 / Stock Tokens / RWA) = distribution Context — not a new trading sleeve (`no_new_rh_sleeve: true`)
- Continue HF-fragile / Damaged Goods caution stack
- `no_integral_solver: true` / `no_strategy_code: true`

Wire `load_k191_notes` + merge in `build_monitor_macro_weather_extras`.

### 2) K193 log-only macro weather
Add `k193:` to `config/k155_operator_notes.yaml`:
- FFJ (arXiv 2607.20645): agent news triage not deployment-ready — explicit false-positive budget; prefer low-FP models; human gate required
- CF SPX selling-pressure teaser: title-only is not a signal — confirm livestream/report before overnight posture change
- Clarity Act / WuBlock = macro/crypto noise for XSP unless RH Chain overlap — awareness only
- `no_integral_solver: true` / `no_strategy_code: true`

Wire `load_k193_notes` + merge (after k191 so later overnight/constraints win if both set).

### 3) Tests
Extend `tests/test_k155_macro_weather_notes.py` (load / includes / from_prod / run_monitor) for both versions. Update overnight overwrite comments if `lane_a_overnight` keys change.

### 4) Hygiene
Lint + focused pytest + commit + push → CI green. No `LIVE_*`. Do not commit `_local/`, `logs/`, `.env`.

## Done when
- `k191_version` and `k193_version` in monitor extras offline
- Focused pytest + CI green on `origin/main`
