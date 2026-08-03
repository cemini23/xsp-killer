# Plan — prod briefs → XSP Killer (2026-08-03)

**Status:** DONE (Grok)

**Hard stops:** `LIVE_*` false; no diffusion training/serving stack in RH paths; no strategy/gate flips from teasers alone; no secrets.

## Brief triage

| Brief | Action |
|-------|--------|
| **K219** IVS diffusion+SAAM + Moontower inevitability + CF Warsh/Bessent | CODE: log-only `k219` weather extras (ideas only; no diffusion vendor) |
| K213 Warsh / Capital Flows | Already shipped (`1faae2c`) |
| K214 WuBlock term premium | Already shipped (`64ae1c0`) |
| K215 Macro inflection + WuBlock + Warsh video | Already shipped (`64ae1c0`) |
| K218 TencentDB Agent Memory | Already shipped (extract only, `9018b6c`) |
| PM briefs | Skip |
| Harness | Skip |

## Implement

1. Keep brief copies: `briefs/xsp-k219-ivs-diffusion-saam.md` + `briefs/2026-08-03_k219-ivs-diffusion-saam.md`.
2. YAML `k219:` in `config/k155_operator_notes.yaml` — overnight `keep_tight_vs_k215` + `no_posture_change_on_teaser`.
3. `load_k219_notes` + merge in `build_monitor_macro_weather_extras` (after k215).
4. Tests in `tests/test_k155_macro_weather_notes.py` (load / includes / from_prod / run_monitor versions+keys; overnight overwrite).
5. Focused pytest → commit → push `main` → CI green on HEAD.

## Non-goals

- Do not vendor a diffusion IVS training/serving stack.
- Do not add aisuite/RH adapters.
- Do not flip strategy gates or LIVE Discord from these teasers.
