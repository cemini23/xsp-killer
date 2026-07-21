# Plan — prod briefs → XSP Killer (2026-07-21)

**Status:** DONE (Cursor — Grok out until 2026-07-24)

**Sources scanned:** `/opt/cemini/briefs/*2026-07-2[0-1]*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH sleeve; no integral solvers; no strategy gate flips from weather notes.

## Route
- **Lane:** hard (log-only weather CODE, mirror K177)
- **Executor:** Cursor (Grok CLI/Build unavailable until Jul 24)

## Brief triage

| Brief | Action |
|-------|--------|
| **K178** `xsp-2026-07-21_k178-capital-flows-equity-cliff.md` (cemini, **new**) | CODE: log-only `k178` extras (mirror K177). Brief says "**No code**" → weather notes only. |
| K177 paid DAMAGED GOODS + Moontower | Already shipped (`f57dc96`) |
| K174 / K173 / K172 / K170 | Already shipped |
| Money-path cursor-audit harden | Already shipped (`05fb44e` / `83762fe`) |
| `pm-2026-07-21_k178-ice-okx-closing-bell` | Skip — PM/Kalshi, not XSP |
| K197–K201 harness / policy | Skip — cemini agent harness, not XSP |

## Implement (safe CODE)

### 1) K178 log-only macro weather
Add `k178:` to `config/k155_operator_notes.yaml`:
- CF Jul 21 equity-cliff teaser: SPX −2.18% from ATH; flow-driver + HF complacency next — **do not chase** on free teaser alone; wait paid flow picture
- Keep Lane A overnight tight vs K177 Damaged Goods / momentum caution
- CME single-stock futures webinar = future leverage channel Context only (`no_product_change: true`)
- `no_integral_solver: true` / `no_strategy_code: true`

Wire `load_k178_notes` + merge in `build_monitor_macro_weather_extras`.

Tests in `tests/test_k155_macro_weather_notes.py`.

### 2) Hygiene
Lint + focused pytest + commit + push → CI green. No `LIVE_*`.

## Done when
- `k178_version` in monitor extras offline
- Focused pytest + CI green on `origin/main`
