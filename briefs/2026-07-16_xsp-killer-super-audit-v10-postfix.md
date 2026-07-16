---
title: XSP Killer — SUPER AUDIT v10 Post-Fix Report
type: brief
tags: [super-audit, xsp-killer, backtest, uw, post-fix, verification]
created: 2026-07-16
updated: 2026-07-16
target: main
---

# XSP Killer — SUPER AUDIT v10 Post-Fix Report

**Audit:** `briefs/2026-07-16_xsp-killer-super-audit-synthesis-v10.md`  
**Plan:** `docs/superpowers/plans/2026-07-16-super-audit-v10-fixes.md`  
**Implemented range:** `06ba819..19f1dce`  
**Final premium review:** **APPROVED**

## Outcome

All confirmed v10 code defects were fixed. The optimizer is now materially safer and more honest, but the empirical strategy conclusion remains unchanged:

> **RESEARCH ONLY. No statistically credible edge. Live RH entries and exits remain NO-GO.**

No variant was activated. No `LIVE_*` gate was enabled.

## Fixes landed

1. **Causal Stage B contexts**
   - Daily regime uses prior completed daily sessions, not 15-minute closes.
   - Primary TA uses completed 1-hour bars.
   - Current-day daily closes and incomplete hourly buckets cannot influence a 15:45 decision.
   - TA enrichment failures fail closed instead of falling back to raw 15-minute TA.

2. **Validation and statistical integrity**
   - Added contiguous train/validation/untouched-test evaluation.
   - Purged trades crossing split boundaries.
   - Refinement uses train data; finalist ranking uses validation; final gates use test.
   - Added shared-session family-wise max-statistic MCPT.
   - Behaviorally identical cells no longer manufacture stable windows or consume finalist quotas.
   - Zero/thin/zero-mean/residual Stage B results cannot confirm an edge.
   - Negative train/validation/test/full results block confirmation.
   - Modeled BS-lite pricing is explicitly non-promotable.

3. **P&L and residual integrity**
   - End-of-series daily exits use the same slippage-aware exit-fill economics as normal exits.
   - Stage B reports unresolved exposure without fabricating closed trades.
   - Residual positions block research-survivor gates.

4. **Runtime/backtest parity**
   - Added shared calendar-backed XSP session counting.
   - Runtime and replay support the same `max_hold_sessions` rule.
   - Holiday, weekend, Sunday GTH, DST, and early-close cases are tested.
   - Forced exits are session-aware and do not require a mark; TP/SL still require valid pricing.
   - Active variants retain a zero/unset session cap.

5. **Strict UW and cache honesty**
   - `--mode uw` is strict by default.
   - Fixture fallback requires an explicit research override.
   - Cache metadata includes identity, timestamps, bar bounds, and CSV SHA-256.
   - Stale, future-dated, mismatched, or legacy unverified caches are rejected by strict runs.
   - Refresh behavior and cache status are recorded in reports.

6. **RH token safety**
   - Default token paths moved outside the repository/OneDrive.
   - Windows uses Local AppData; POSIX uses the user state directory.
   - Environment/config precedence remains supported.
   - Repository and registered OneDrive roots fail closed without an explicit development-only override.
   - The token-sync helper uses the same safe path policy.

7. **Windows state safety**
   - Variant state writes use reentrant sidecar locks plus atomic replacement.
   - Locks cover the complete load→modify→write transaction.
   - Lock acquisition failures fail closed.
   - Public entry/monitor calls reload persisted state inside the lock instead of accepting stale caller snapshots.

## Verification

- Full Windows suite: **620 passed, 1 skipped**.
- Final focused premium review: **APPROVED**, no Critical or Important findings.
- Substrate invariant check: all listed modules **OK**.
- Git diff check: clean.
- Main CI: green through the final reviewed strategy commit; final lock commits use the same passing workflow and are verified separately before handoff.
- Fresh strict-UW run: exit 0; true UW sources only; no fixture fallback.

## Fresh strict-UW result

**Report:** `reports/backtest/regime_hold_20260716T220221Z.md` (local research artifact)

- Daily coverage: 252 bars / 252 sessions, 2025-07-16 through 2026-07-16.
- Intraday coverage: 1,500 bars / 24 sessions, including GTH/RTH/Curb.
- Recommendation: **RESEARCH ONLY**.
- Edge reason: `cross_split_mean_not_positive`.
- Stable parameter windows: **0**.
- Family-wise p-values for shown leaders: approximately **0.28–0.48**, all failing 5%.
- Stage B means: all negative, approximately **−0.43% to −10.51%**.
- Sensitivity: every shown finalist had **0/4 positive IV seeds** and failed 1.5× slippage positivity.
- Example leading validation cell (28 DTE, TP 20%, SL 30%, GREEN, 3-session cap):
  - train: **−11.58%**
  - validation: **+9.67%**
  - untouched test: **−6.68%**
  - full: **−6.61%**
  - Stage B: **−9.92%**, 7 closed trades, 1 residual
  - family-wise p: **0.2817**

The revised report now surfaces the positive validation/negative train-test-full conflict in its first table instead of presenting a holdout-only leader.

## Remaining non-code limitations

- UW still returned only one year of daily bars and 24 intraday sessions.
- Premiums remain BS-lite modeled, not historical XSP chain fills.
- XNYS is used as the documented Cboe holiday proxy.
- Twenty-four Stage B sessions are insufficient for promotion inference.

These are data/fidelity constraints, not hidden implementation defects. They keep all optimizer output in research-only posture.

## Deployment posture

| Surface | Decision |
|---------|----------|
| Existing paper soak | CONDITIONAL GO |
| Strict UW research | GO for research only |
| RH MCP reads | CONDITIONAL GO with correct account/token pin |
| Live exits | NO-GO |
| Live entries | NO-GO |
| Activate generated candidate | NO |
