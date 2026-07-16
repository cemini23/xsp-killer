---
title: XSP Killer — SUPER AUDIT v10 Synthesis
type: brief
tags: [super-audit, xsp-killer, backtest, uw, optimizer, prod-ship]
created: 2026-07-16
updated: 2026-07-16
target: main
---

# XSP Killer — SUPER AUDIT v10 Synthesis

**Date:** 2026-07-16 · **HEAD audited:** `11571b6` · **Mode:** `prod-ship`  
**Scope:** XSP bot runtime, UW backtest, regime/hold optimizer, session-aware intraday replay, reporting, and recent integration.

## Panel

| Slot | Channel | Role | Model | Verdict |
|------|---------|------|-------|---------|
| 1 | Cursor | agentic-reasoning | Fable 5 → Opus 4.8 → Kimi K2.7 | **Unavailable:** Cursor usage limit on all attempts; no vote |
| 2 | Cursor | code-implementation | GPT-5.6 Sol | Paper WARN · Backtest FAIL · Live FAIL |
| 3 | Cursor | third-lens | Gemini 3.1 Pro | Paper PASS · Backtest FAIL · Live WARN |
| 4 | API | adversarial | Grok 4.3 | Paper WARN · Backtest WARN · Live FAIL |
| 5 | API | deep-reasoning | DeepSeek Reasoner | Paper WARN · Backtest WARN · Live FAIL |

The audit completed **4 independent reports out of 5 planned**. The missing Anthropic/Kimi Cursor seat is recorded as unavailable, not counted as agreement.

> **Overall: REWORK for optimizer decision-usefulness; NO-GO for live RH writes.** Existing inactive paper variants may continue soaking. UW runs remain exploratory. No backtest candidate should be activated.

## Strong consensus (4/4 completed)

1. **No live RH entries or exits.** The strategy has no confirmed edge, Stage B is underpowered, and backtest/runtime parity is incomplete.
2. **The generated candidate must remain inactive.** All auditors confirmed that generation is human-only and does not flip live gates.
3. **Stage B is too small for promotion claims:** 1,500 bars, 24 sessions, six closed trades per finalist, with negative means.
4. **Synthetic BS-lite premiums are relative research signals, not evidence of executable XSP fills.**
5. **Paper operation may continue only as measurement/soak, not as promotion proof.**

## Confirmed P0 findings

### 1. Stage B computes daily/regime and primary TA on the wrong timeframe

`run_intraday_backtest()` applies `_regime_series()` directly to 15-minute closes and applies the 20-period Bollinger calculation directly to 15-minute bars. Runtime rules specify `primary_timeframe: 1h`; the regime model uses 21/50 periods intended as daily context.

**Evidence:** `xsp_killer/backtest/intraday.py:288-312`, `config/lane_a_rules.yaml:47-52`.

**Impact:** Stage B validates a materially different signal from the live bot. A 50-bar regime average becomes roughly two 15-minute trading days rather than 50 daily sessions.

**Fix:** Build completed daily closes for regime context and completed 1-hour bars for primary TA, then align/forward-fill only completed values onto each 15-minute decision bar. Add anti-lookahead tests at daily/hourly boundaries.

### 2. Zero-trade intraday validation can pass the edge gate

`_summarize_intraday()` encodes no trades as mean `0.0`. `edge_confirmed()` rejects only means below zero and has no Stage B minimum-trade gate.

**Evidence:** `scripts/optimize_regime_hold.py:297-313`, `xsp_killer/backtest/regime_hold.py:963-998`.

**Impact:** A finalist with zero validated trades can be reported as `EDGE-CONFIRMED` if its other gates pass.

**Fix:** Require a positive intraday holdout mean, a configurable minimum number of closed intraday trades, and zero unresolved residual positions.

### 3. The optimized hold cap has no runtime equivalent

Stage A and Stage B enforce `max_hold_sessions`; generated YAML deliberately strips it and labels it as a backtest-only kwarg. Runtime `LaneRules`/monitor behavior cannot execute the optimized hold strategy.

**Evidence:** `xsp_killer/backtest/engine.py:351-361`, `xsp_killer/backtest/intraday.py:348-362`, `xsp_killer/backtest/regime_hold.py:1001-1055`.

**Impact:** Pasting/activating the candidate would run a different exit policy from the tested strategy.

**Fix:** Add a validated runtime `max_hold_sessions` rule using shared exchange-session accounting, or formally prohibit edge-confirmed/promotable output for hold-cap candidates. Runtime/replay parity tests are mandatory.

## Confirmed P1 findings

1. **Selection holdout is reused for tuning.** Coarse ranking, seed selection, refinement, reranking, stable-window discovery, and finalist MCPT all consume the same holdout (`regime_hold.py:528-598`). Replace with train → validation selection → untouched temporal test.
2. **MCPT is conditional on top-K selection.** P-values are not family-wise adjusted after the grid search. Use nested/max-statistic permutation or clearly label the current p-values exploratory.
3. **Residual intraday positions are right-censored.** They are noted but omitted from means/counts (`intraday.py:498-500`). Block confirmation when residuals remain and report conservative terminal MTM separately.
4. **Daily end-of-series percentage ignores exit slippage.** Residual `net_pnl_pct` uses raw mark while dollar P&L uses `exit_fill_premium` (`engine.py:498-545`). Use one economics path.
5. **The edge gate ignores negative train/full performance.** A lucky positive selected holdout can confirm despite negative train/full metrics. Require explicit cross-split robustness.
6. **“Stable windows” can be behavioral clones.** Adjacent parameter labels may produce identical trades. Deduplicate by entry/exit signature before claiming robustness.
7. **The Markdown leader table hides train/full disagreement.** Put train, validation/test, full, Stage B, residual, and MCPT status together in the first decision table.
8. **`--mode uw` can still fail open unless `--require-uw` is remembered.** Make UW mode strict by default and require an explicit `--allow-fixture-fallback` research override.
9. **UW cache freshness is not validated.** Add requested-end/max-age metadata or a refresh flag so a stale period cache cannot masquerade as a current run.
10. **Exchange-session keys are heuristic, not calendar-backed.** Add holiday/early-close cases and use a shared exchange calendar before runtime hold-cap promotion.

## Findings rejected as stale or unsupported

- **Malformed `position_effect` bypass:** already fixed; every leg is explicitly rejected unless effect is `open` or `close` (`robinhood_mcp.py:648-664`).
- **Review transport success grants placement:** already fixed by `_review_outcome_approved()` (`robinhood_mcp.py:397-457,584-595`).
- **Live exit fan-out:** current monitor gates variant MCP reviews to `LIVE_VARIANT_ID` (`lane_a_monitor.py:1079-1095`).
- **Windows `fcntl` blocker:** current lock layer supports `portalocker`, `fcntl`, and `msvcrt` and fails loudly when none exist (`fs_lock.py:1-130`).
- **Fixture fallback is hidden in the latest run:** false; the audited real run used strict UW and reported `source: uw`. The remaining issue is unsafe CLI ergonomics for future runs.
- **No future leakage at all:** unsupported. Signals appear causal, but selection leakage remains because the same holdout is repeatedly optimized.

## Statistical validity

- **Sample adequacy:** one year of daily bars and 24 intraday sessions cannot establish a regime-dependent options edge.
- **Selection bias:** holdout-guided refinement and top-K-only MCPT make current significance optimistic.
- **Synthetic pricing:** fixed-IV BS-lite omits skew, IV changes, bid/ask width, GTH liquidity, and historical XSP chain fills.
- **Censoring:** open Stage B positions are excluded from closed-trade means.
- **Current result:** positive holdout cells conflict with negative train/full and negative intraday results. The correct conclusion remains **no credible edge**.

## Runtime integration verdict

Entry DTE, strike, regime, TP, and SL map into runtime configuration. The central newly optimized field, session hold cap, does not. Therefore optimizer snippets are safe only because they are inactive and explicitly research-only; they are not executable strategy definitions.

## Deployment recommendation

| Surface | Decision | Conditions |
|---------|----------|------------|
| Paper-only | CONDITIONAL GO | Existing inactive/soak variants; measurement only |
| UW research | CONDITIONAL GO | Strict UW, corrected timeframes/gates, no promotion claims |
| RH MCP reads | CONDITIONAL GO | Correct token/account pin; write flags false |
| Live exits | NO-GO | Safety posture plus executable/validated strategy parity required |
| Live entries | NO-GO | Same, plus statistically credible edge and paper confirmation |

## Ranked patch order

1. Correct Stage B daily regime and 1-hour primary TA without lookahead.
2. Make edge confirmation reject zero/thin/residual/negative cross-split validation.
3. Repair end-of-series economics and report residual exposure.
4. Separate train/validation/untouched test and adjust grid-search significance.
5. Deduplicate behavioral clones and tighten stable-window semantics.
6. Implement shared runtime/backtest exchange-session hold caps with calendar tests.
7. Make UW mode strict by default; add cache freshness controls.
8. Rewrite the decision table and disclaimers around exploratory p-values.

## Re-audit gate

After these patches: run targeted tests, the full suite, Ruff, and a fresh strict-UW Stage A/B run. Do not repeat a five-model council for tiny follow-ups; perform one premium post-fix review focused on parity, leakage, and edge-gate tests.
