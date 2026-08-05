# Plan — prod briefs → XSP Killer (2026-08-05)

**Status:** DONE (Claude)

**Hard stops:** `LIVE_*` false; **not a live pricer wire** — no NNLCI/Heston NN serving in RH monitors; no printed SOX/IGV levels from Macro teaser; no GuruWatcher arm from teasers; no strategy/gate/LIVE_* flips; keep prior constraints (no_diffusion_vendor, no_cf_workers_vendor, no_live_auto_calibrator, no_neural_operator_serving); no secrets.

## Brief triage

| Brief | Action |
|-------|--------|
| **K223** NNLCI options pricing + CF FX teaser + Macro SOX/yields | CODE: log-only `k223` weather extras (offline research only; no live pricer wire) |
| K221 Macro Charts + K222 VIX/LSV | Already shipped (`6bd046c`) |
| Harness K241–K248 | Skip |
| PM briefs | Skip |

## Implement

1. Keep brief copy: `briefs/xsp-k223-nnlci-fx-macro.md`.
2. YAML `k223:` in `config/k155_operator_notes.yaml` after k222 — overnight chain ends `keep_tight_vs_k222` + `no_posture_change_on_teaser`.
3. `load_k223_notes` + merge in `build_monitor_macro_weather_extras` (k223 merged last → overnight ends keep_tight_vs_k222; constraints gain no_live_pricer_wire).
4. Tests in `tests/test_k155_macro_weather_notes.py` (load / includes / from_prod / run_monitor versions+keys; from-prod overnight overwrite to k222 keys).
5. Focused pytest → commit → push `main` → CI green on HEAD.

## Non-goals

- Do not wire NNLCI / coarse+refined mesh NN / Heston barrier pricing as a live pricer in RH paths.
- Do not print SOX/IGV numeric levels from the Macro teaser, or arm GuruWatcher from teasers alone.
- Do not flip strategy gates, LIVE Discord, or LIVE_* flags.
- No diffusion / CF Workers / live auto-calibrator / neural-operator serving (prior constraints retained).
