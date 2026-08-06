# Plan — prod briefs → XSP Killer (2026-08-06)

**Status:** DONE (Claude)

**Hard stops:** `LIVE_*` false; **not a live calibrator** — no new solver / tabular LLM prediction (K241); Capital Flows 2026-08-06 global-economy post was RSS **teaser only** — do not invent claims; no strategy/gate/LIVE_* flips; GREEN `playbook_snapshot` gates unchanged; keep prior constraints (no_diffusion_vendor, no_cf_workers_vendor, no_live_auto_calibrator, no_neural_operator_serving, no_live_pricer_wire); no secrets.

## Brief triage

| Brief | Action |
|-------|--------|
| **K225** Wu July VC + Macro hard-assets regime | CODE: log-only `k225` weather extras (CeFi/tokenization VC context; tactically bullish Tech/AI + strategically bullish hard assets; CF global-economy teaser = RSS-only) |
| K224 Klement AI data-centre capex vs earnings boom | Already shipped (`da8ab81`) |
| Harness K244–K253 | Skip |
| PM K225 Kalshi/FanDuel | Skip |

## Implement

1. Keep brief copy: `briefs/xsp-k225-wublock-july-vc-macro.md`.
2. YAML `k225:` in `config/k155_operator_notes.yaml` after k224 — overnight chain ends `keep_tight_vs_k224` + `no_posture_change_on_teaser`; constraints retained with `no_tabular_llm_prediction`.
3. `load_k225_notes` + merge in `build_monitor_macro_weather_extras` (k225 merged last → overnight ends keep_tight_vs_k224; three content keys: `wublock_july_vc_cefi`, `macro_aug6_hard_assets`, `cf_global_economy_teaser`).
4. Tests in `tests/test_k155_macro_weather_notes.py` (load / includes / from_prod / run_monitor versions+keys; from-prod overnight overwrite to k224 keys; isolated k224 includes fixture still asserts keep_tight_vs_k223).
5. Focused pytest → commit → push `main` → CI green on HEAD.

## Non-goals

- Do not auto-trade from CeFi/tokenization narrative; basis/inventory awareness only.
- Do not invent Capital Flows global-economy claims beyond the RSS teaser.
- Do not flip strategy gates, LIVE Discord, or LIVE_* flags; GREEN `playbook_snapshot` gates unchanged.
- No diffusion / CF Workers / live auto-calibrator / neural-operator serving / live pricer wire (prior constraints retained); no new solver or tabular LLM prediction (K241).
