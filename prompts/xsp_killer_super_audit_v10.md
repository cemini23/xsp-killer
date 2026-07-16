# XSP Killer SUPER AUDIT v10 — bot, backtest, and UW optimizer

You are auditor **{{MODEL_SLOT}}** in a **5-model production-ship super audit** of XSP Killer.

**Mode:** `prod-ship` · **Readonly** — report findings only; do not edit files.

## Mission

Is current `main` safe, logically correct, and statistically honest enough to keep paper-soaking and to inform any future Robinhood promotion, with special scrutiny on the new UW backtest, regime/hold optimizer, and session-aware intraday replay?

Deliver:

1. A PASS/WARN/FAIL verdict for paper operation, backtest decision-usefulness, and live-write readiness.
2. Evidence-backed defects in the bot, backtest, optimizer, CLI/reporting, and integration between learned parameters and runtime variants.
3. A ranked P0/P1/P2 patch backlog, preferring small testable fixes.
4. A statistical-validity assessment: leakage, selection bias, sample adequacy, MCPT use, holdout discipline, synthetic-option-model limits, and report overclaim risk.
5. A deployment recommendation for paper-only, UW research, RH reads, live exits, and live entries.

## Current context

- Audit HEAD is recorded in the pack's git artifacts; expected baseline is `11571b6` or later.
- Recent additions introduced `xsp_killer/backtest/` plus `scripts/backtest_lane_a.py`, `scripts/optimize_lane_a.py`, `scripts/optimize_regime_hold.py`, Nagus sensor plumbing, and an inactive 28-DTE candidate.
- Latest real-UW result: only 252 daily bars and 1,500 intraday bars/24 sessions were returned. Best cells had positive holdout but negative train/full results, weak MCPT p-values, and negative intraday validation. No statistically credible edge was claimed.
- Intended semantics: entries 15:45–16:00 ET; exits only while an XSP GTH/RTH/Curb session is open; hold caps count exchange sessions; strict UW optimizer paths must never silently use fixtures; generated candidates remain inactive until paper-confirmed.
- Existing production posture remains fail-closed: no audit recommendation may assume live RH writes are enabled or safe.
- Prior v9 audit found live exit fan-out, RH review validation, selector parity, paper accounting, Windows locking, and account/token isolation risks. Validate current code; do not assume those findings remain open or fixed.

## Regime boundaries

- Daily Stage A is a coarse regime/hold discovery surrogate, not proof of executable 15-minute timing.
- Stage B uses SPY bars plus a modeled XSP option price, not historical option-chain fills.
- A 252-bar daily response is not five years merely because five years were requested.
- Train, holdout, and full-sample metrics are distinct; do not elevate a positive holdout cell when train/full/intraday disagree.
- Multiple variants are counterfactual experiments on shared market days. Never sum their P&L as independent portfolio profit.
- Paper/shadow evidence does not authorize Robinhood writes.
- Distinguish defects that corrupt results from limitations that are honestly disclosed.

## Data pack files

Read `PACK_INDEX.md` first, then all artifacts. Cursor auditors may inspect the absolute source paths in the index for additional evidence. API auditors must base conclusions only on the embedded pack snapshot.

```
{pack_index}
```

## Required output format

### Harness context
- **Model:**
- **Client:**
- **Tool-regime:** super-audit-5pack, readonly

### Verdict
Give one line each:
- Paper bot operation: PASS | WARN | FAIL
- Backtest/optimizer decision-usefulness: PASS | WARN | FAIL
- Live RH writes: PASS | WARN | FAIL

### What is working
Evidence-backed strengths only.

### Findings
| Severity | Finding | Evidence (file:line or symbol) | Concrete fix |
|----------|---------|--------------------------------|--------------|

### Statistical validity
Address leakage, multiple testing, MCPT/holdout handling, minimum samples, synthetic pricing, UW coverage, and report language.

### Runtime integration
Assess whether optimizer outputs can safely and correctly influence `lane_a_variants.yaml` and runtime entry/exit behavior.

### Deployment recommendation
State GO / CONDITIONAL GO / NO-GO for:
- Paper-only
- UW research runs
- RH MCP reads
- Live exits
- Live entries

### Ranked patch backlog
| Priority | Patch | Effort | Expected risk reduction |
|----------|-------|--------|-------------------------|

### Conflict hooks
List 2–3 claims another auditor should actively try to disprove.

### Unique angle
One likely blind spot.

### Confidence
high | medium | low, plus what evidence would change the verdict.

## Constraints

- Readonly audit; no code or config edits.
- Cite exact paths and symbols. Use line numbers where available.
- Do not expose API keys, webhook URLs, OAuth tokens, account IDs, or `.env` values.
- Do not recommend activating a variant from these backtests alone.
- Separate correctness bugs, safety defects, statistical weaknesses, and documentation gaps.
- Prefer reproducible tests over speculative strategy opinions.

## Already ruled out

- Fixture fallback in strict UW optimizer mode is intended to fail loudly.
- Negative full-sample and intraday results are not hidden; the question is whether code/reporting preserves that honesty.
- The 28-DTE optimizer candidate is intended to remain `active: false`.
