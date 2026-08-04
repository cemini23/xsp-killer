# Plan — prod briefs → XSP Killer (2026-08-04)

**Status:** DONE (Grok)

**Hard stops:** `LIVE_*` false; no Cloudflare Workers/D1/MyTube vendor into RH monitors; no live auto-calibrator / diffusion / neural-operator serving in RH paths; no strategy/gate/LIVE_* flips; no GuruWatcher arm from teasers alone; no secrets.

## Brief triage

| Brief | Action |
|-------|--------|
| **K221** Macro Charts Aug 3 + CF misdirection livestream | CODE: log-only `k221` weather extras (regime color + awareness only; no CF Workers vendor) |
| **K222** VIX-first + amortizing LSV calibration | CODE: log-only `k222` weather extras (awareness only; no live auto-calibrator / neural-op serving) |
| K219 IVS SAAM + Moontower + CF | Already shipped (`139b7d8`) |
| K218 TencentDB Agent Memory | Already shipped (extract only, `9018b6c`) |
| Harness K236–K243 | Skip |
| PM briefs | Skip |

## Implement

1. Keep brief copies: `briefs/xsp-k221-macro-capital-flows.md`, `briefs/2026-08-04_k221-macro-capital-flows.md`, `briefs/xsp-k222-vix-lsv-calibration.md`, `briefs/2026-08-04_k222-vix-lsv-calibration.md`.
2. YAML `k221:` + `k222:` in `config/k155_operator_notes.yaml` after k219 — overnight chain ends `keep_tight_vs_k221` + `no_posture_change_on_teaser`.
3. `load_k221_notes` / `load_k222_notes` + merge in `build_monitor_macro_weather_extras` (k222 merged last → overnight ends keep_tight_vs_k221).
4. Tests in `tests/test_k155_macro_weather_notes.py` (load / includes / from_prod / run_monitor versions+keys; from-prod overnight overwrite to k222 keys).
5. Focused pytest → commit → push `main` → CI green on HEAD.

## Non-goals

- Do not vendor Cloudflare Workers / D1 / MyTube / instant-site stacks into RH monitors or xsp order paths.
- Do not wire a live auto-calibrator, diffusion train/serve, or neural-operator serving in RH paths.
- Do not flip strategy gates, LIVE Discord, or arm GuruWatcher levels from these teasers alone.
