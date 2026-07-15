## Target

CeminiSuite — XSP killer bot (Robinhood long-call lanes A/B).

## Summary

K167 **Steal** from Macro Charts 2026-07-15: SOX/MU bounce watch + soft CPI; **oil↑ vs 2YR↓** divergence as overnight risk flag; software/IGV strength after IBM wipe is context only. Moontower: vega-neutral iron butterfly = **long volga** framing for Lane B only — **no auto structure**. Log-only Phase 0; does **not** change GREEN/YELLOW/RED gate logic. Pairs with K162 no-chase semis.

## Operator checklist

1. **Oil vs 2YR:** log divergence; prefer tighter overnight criteria until 2YR trend clarifies (not an auto block).
2. **SOX/MU bounce ≠ chase** crowded semis/memory into Lane A overnight (pair K162).
3. **Soft CPI:** supportive disinflation context; still require cross-asset confirms before size-up.
4. **Volga:** Lane B LEAPS / vol-sensitivity mental model only; `no_auto_structure: true`.
5. **Software/IGV:** context only — not a RH software sleeve mandate.
6. **No integral solvers. No LIVE_* flips.**

## Config & code

- `config/k155_operator_notes.yaml` — `k167` block (`oil_vs_2yr`, `sox_mu_bounce`, `soft_cpi`, `moontower_volga`, `software_igv`)
- `xsp_killer/macro_weather_notes.py` — `load_k167_notes`, K167 passthrough in `build_monitor_macro_weather_extras`
- `xsp_killer/lane_a_monitor.py` — attaches `macro_weather_extras` to monitor JSON (log-only)
- `tests/test_k155_macro_weather_notes.py` — load + merge + monitor attach

## Sources

- `/opt/cemini/briefs/xsp-2026-07-15_k167-macro-charts-sox-cpi-moontower-volga.md`
