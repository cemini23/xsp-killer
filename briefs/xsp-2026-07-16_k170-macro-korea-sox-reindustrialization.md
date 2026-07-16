## Target

CeminiSuite — XSP killer bot (Robinhood long-call lanes A/B).

## Summary

K170 **Steal** from Macro Charts Jul 16: Korea levered-ETF clamp + Memory late-Q3 risk; SOX ~$12k support; DXY May-uptrend / ~100.50 break test; soft PPI. Capital Flows: US re-industrialization / defense stack as rates backdrop — **regime context only, no new RH sleeve**. Theory shelf: SDF-from-options + Dupire SPDE = **REFERENCE only**. Turbovec = optional local RAG experiment — soak first, no prod index swap. Log-only Phase 0; does **not** change GREEN/YELLOW/RED gate logic. Pairs with K162/K167 no-chase semis.

## Operator checklist

1. **Korea / Memory semis:** overnight Lane A conditional on SOX holding ~12k and Korea liquidity not cascading.
2. **SOX ~$12k:** support watch for semis bounce framing.
3. **DXY breakdown:** log May-uptrend / 100.50 break test as risk-regime flag — prefer tighter overnight criteria until close confirms.
4. **Re-industrialization / defense:** regime context for chips/industrials only — `no_new_rh_sleeve: true`.
5. **Theory shelf:** SDF/Dupire = reference only — `no_integral_solver: true`.
6. **Turbovec:** optional local experiment — `no_prod_index_swap: true`.
7. **No integral solvers. No Inkling weights. No LIVE_* flips.**

## Config & code

- `config/k155_operator_notes.yaml` — `k170` block (`korea_memory_semis`, `sox_support`, `dxy_breakdown`, `us_reindustrialization`, `theory_shelf`, `turbovec`)
- `xsp_killer/macro_weather_notes.py` — `load_k170_notes`, K170 passthrough in `build_monitor_macro_weather_extras`
- `xsp_killer/lane_a_monitor.py` — attaches `macro_weather_extras` to monitor JSON (log-only)
- `tests/test_k155_macro_weather_notes.py` — load + merge + monitor attach

## Sources

- `/opt/cemini/briefs/xsp-2026-07-16_k170-macro-korea-sox-reindustrialization.md`
- `@wiki/sources/macro-charts-paid-forward-2026-07-16-korea-sox-dxy-metals.md`
- `@wiki/sources/substack-rss-capital-flows-2026-07-16-reindustrialization-usa.md`
- `@wiki/entities/tools/turbovec.md`
