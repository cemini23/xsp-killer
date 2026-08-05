# Plan — prod briefs → XSP Killer (2026-08-05)

**Status:** DONE (Claude)

**Hard stops:** `LIVE_*` false; **not a live pricer wire** — no new solver/tabular LLM prediction (K241); no printed SMH/SOX/NVDA levels from this teaser (GuruWatcher-primary for Aug 4 SMH plan); no strategy/gate/LIVE_* flips; keep prior constraints (no_diffusion_vendor, no_cf_workers_vendor, no_live_auto_calibrator, no_neural_operator_serving, no_live_pricer_wire); no secrets.

## Brief triage

| Brief | Action |
|-------|--------|
| **K224** Klement AI data-centre capex vs earnings boom | CODE: log-only `k224` weather extras (mean-reversion / multiple-compression risk; not a timed short) |
| K223 NNLCI + CF FX teaser + Macro SOX/yields | Already shipped (`5124f50`) |
| Harness K241–K248 | Skip |
| PM briefs | Skip |

## Implement

1. Keep brief copy: `briefs/xsp-k224-klement-ai-datacentre.md`.
2. YAML `k224:` in `config/k155_operator_notes.yaml` after k223 — overnight chain ends `keep_tight_vs_k223` + `no_posture_change_on_teaser`; constraints gain `no_tabular_llm_prediction`.
3. `load_k224_notes` + merge in `build_monitor_macro_weather_extras` (k224 merged last → overnight ends keep_tight_vs_k223; constraints gain no_tabular_llm_prediction).
4. Tests in `tests/test_k155_macro_weather_notes.py` (load / includes / from_prod / run_monitor versions+keys; from-prod overnight overwrite to k223 keys; isolated k223 includes fixture still asserts keep_tight_vs_k222).
5. Focused pytest → commit → push `main` → CI green on HEAD.

## Non-goals

- Do not wire Klement AI-capex data-centre economics as a timed short or a live signal.
- Do not print SMH/SOX/NVDA numeric levels from this teaser; Aug 4 Macro SMH plan remains last printed unless operator extracts new levels.
- Do not flip strategy gates, LIVE Discord, or LIVE_* flags.
- No diffusion / CF Workers / live auto-calibrator / neural-operator serving / live pricer wire (prior constraints retained); no new solver or tabular LLM prediction (K241).
