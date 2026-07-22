# Plan — prod briefs → XSP Killer (2026-07-22)

**Status:** DONE (Cursor — Grok out until 2026-07-24)

**Sources scanned:** `/opt/cemini/briefs/*2026-07-2[1-2]*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH sleeve; no integral solvers; no strategy gate flips from weather notes.

## Route
- **Lane:** hard (log-only weather CODE, mirror K178)
- **Executor:** Cursor (Grok CLI/Build unavailable until Jul 24)

## Brief triage

| Brief | Action |
|-------|--------|
| **K182** `xsp-2026-07-22_k182-illiquid-iv-map-hf-fragile.md` (cemini, **new**) | CODE: log-only `k182` extras (mirror K178). Brief says "**No code**" → weather notes only. |
| K178 CF equity cliff | Already shipped (`f35c403`) |
| K177 / money-path audit | Already shipped |
| `pm-2026-07-22_k182-aqi-circle-ousd-fragile-tokens` | Skip — PM/Kalshi, not XSP |
| K197–K201 harness / policy | Skip — cemini agent harness, not XSP |

## Implement (safe CODE)

### 1) K182 log-only macro weather
Add `k182:` to `config/k155_operator_notes.yaml`:
- Liquid→illiquid IV map: when Mini-SPX/XSP quotes thin, prefer SPX/ES liquid surface as benchmark mapper — do not force sparse XSP-only calibration
- arXiv 2607.19030 energy crack-spread = methodology Context only (`no_energy_book: true`)
- HF fragile positioning (CF Jul 22): keep Lane A overnight tight; no size-add on bounce until paid flow confirms
- Continues K178 / K177 caution stack
- `no_integral_solver: true` / `no_strategy_code: true`

Wire `load_k182_notes` + merge in `build_monitor_macro_weather_extras`.

Tests in `tests/test_k155_macro_weather_notes.py`.

### 2) Hygiene
Lint + focused pytest + commit + push → CI green. No `LIVE_*`.

## Done when
- `k182_version` in monitor extras offline
- Focused pytest + CI green on `origin/main`
