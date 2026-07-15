# Plan — prod briefs → XSP Killer safe CODE (2026-07-15)

**Sources scanned:** `/opt/cemini/briefs/xsp-*` (esp. K167/K168 today), `/opt/xsp-killer/briefs/*` (mentor book, David ops, v9, K155–K162, prune).  
**Hard stops:** `LIVE_ENTRIES` / `LIVE_EXITS` stay false. No Bonsai/Undici on RH order path (K168). No CEV solvers (K161). No auto-semis (K162/K167).

## Brief triage

| Brief | Relevance | Action |
|-------|-----------|--------|
| Mentor RH book vs paper (`2026-07-15_mentor-…`) | **Lane B gap** — 9/30 ~77 DTE between Lane A max 60 and Lane B ≥180 | CODE: mid-tenor / Lane A⅔ shadow + docs |
| K167 SOX/CPI/oil–2YR/volga (`cemini` today) | Regime flags for overnight | CODE: log-only `k167` extras (extend K155 chain) |
| K168 Bonsai/Undici (`cemini` today) | Explicit **no live RH code** | DOC note only (watchlist) |
| K161/K162 | Already in `k155_operator_notes.yaml` + `macro_weather_notes.py` | Skip (done) |
| K155/K158 SOFR | Already Phase 0 log-only | Skip |
| v9 remaining CODE | Landed in `72150de` | Skip |
| David onsite `2026-07-16_…` | Ops (UW key, OneDrive token, GitHub) | Out of scope |
| Variant prune + Kimi DTE collision | **55dte now active** but 55/60 collide when `dte_max=60` | CODE: extend pick window for 55-target variants |

## Implement (safe CODE only)

### 1) Mentor mid-tenor / Lane A⅔ shadow
- Add **one** inactive-by-default OR carefully capacity-gated active shadow, e.g. `v2_mid_tenor_80dte_atm` (or similar), targeting **~75–90 DTE** (mentor 9/30 class).
- Overrides: `entry.dte_pick: target`, `dte_target: 80`, **`dte_max: 90`** (variant-only via merge — do **not** raise baseline `lane_a_rules.yaml` dte_max for overnight sleeve).
- Prefer ATM / qty 1–2; swing_hold OK. Document sleeve name **Lane A⅔** in `docs/lane-a-brief.md` + strategy diagnosis + short note in mentor brief.
- Capacity: active set is already ~13 with 55dte. Prefer **`active: true` only if** you deactivate one low-priority keep (document which), **else** ship mid-tenor as `active: false` with ops comment “enable after capacity prune” — **prefer active** with pruning `v2_28dte_green_day` or another thin sample keeper if needed to stay ≤12–13.

### 2) K167 log-only macro weather extras
- Add `k167:` block to `config/k155_operator_notes.yaml`: oil↑ vs 2YR↓ risk flag; SOX/MU crowd bounce ≠ chase overnight; soft CPI note; Moontower volga = mental model for Lane B only (`no_auto_structure: true`); software/IGV context.
- Wire `load_k167_notes` + merge in `build_monitor_macro_weather_extras` (same pattern as k161/k162).
- Tests in `tests/test_k155_macro_weather_notes.py`.
- Brief pointer under `briefs/` (xsp steal note syncing cemini K167).

### 3) Fix 55/60 DTE expiry collision for active 55dte shadow
- For variants with `dte_target` in ~50–60 (at least `v2_dip_swing_55dte_otm`): override **`dte_max: 65`** (or 70) so next Friday beyond 60 is eligible and 55 ≠ 60 pick.
- Update `tests/test_operator_dte_stagger.py`: with raised max, 55 and 60 should resolve to **distinct** expiries when 65 exists; keep a documentated test for baseline `dte_max=60` collision behavior.
- Ensure paper `pick_expiration` + RH `select_entry_contract` honor merged `dte_max`.

### 4) K168 watch-only
- One short paragraph in `docs/rh_mcp_claudio.md` or strategy diagnosis: Bonsai/Undici are eval/future REST hedges — **never** on RH place path. No code dependency.

## Done when
- Tests green for macro notes, DTE stagger, variants load.
- Mid-tenor sleeve documented; K167 appears on monitor extras.
- Status brief updated; local commit (no push unless asked). No LIVE_* flips.

## Out of scope
- David OAuth / UW key / GitHub invite.
- Enabling live RH writes.
- Installing Bonsai/Undici runtime.
- Changing Macro Weather GREEN/YELLOW/RED classifier.
