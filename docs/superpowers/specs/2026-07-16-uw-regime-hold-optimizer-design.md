# UW Regime and Hold Optimizer Design

Date: 2026-07-16  
Status: approved design  
Implementation route: premium plan, Grok CLI implementation, local verification

## Goal

Find robust Lane A automation parameters around the observed 28–35 DTE ATM
cluster, focusing on:

- regime rules that admit profitable close-window entries without opening risk
  indiscriminately;
- forced hold periods of 1, 2, 3, 5, and 10 trading sessions;
- entries only from 15:45 through 16:00 ET;
- exits whenever the Cboe XSP session is actually open;
- stability across time splits, IV assumptions, and transaction-cost stress.

The optimizer remains a relative research tool. It cannot promote a variant,
place orders, or change any live-trading gate.

## Current Limitation

The existing two-year UW optimizer uses daily SPY bars. Its entries represent
the daily close, which is a reasonable proxy for the required 15:45–16:00 ET
entry window. Its exits, however, are checked only on subsequent daily closes.
It therefore cannot support the claim that take-profit and stop-loss exits were
available at any point during the XSP session.

The live bot already has the correct session model:

- GTH: 20:15 through 09:25 ET;
- RTH: 09:30 through 16:15 ET;
- Curb: 16:15 through 17:00 ET;
- closed gaps and weekend handling, including the Saturday morning tail and
  Sunday evening reopen.

The optimizer must reuse this session model rather than treating XSP as an
uninterrupted 24/6 market.

## Architecture

### Stage A: Long-History Regime Discovery

Use cached UW daily SPY OHLC to search a bounded regime and hold grid over the
longest reliable period. This stage discovers stable regions; it does not claim
intraday exit fidelity.

Search dimensions:

- DTE target: 21, 28, 35;
- take profit: 10%, 15%, 20%, 25%;
- stop loss: 20%, 30%, 40%;
- maximum hold: 1, 2, 3, 5, 10 trading sessions;
- regime family:
  - GREEN;
  - GREEN or qualified YELLOW;
  - qualified YELLOW only, if supported without changing live semantics;
- yellow trend fraction: 0.40, 0.50, 0.60, 0.75;
- yellow bounce requirement: true or false;
- prior-session SPY filter: none, positive, or non-negative where supported.

The implementation may use coarse-to-fine search to avoid an unbounded
factorial. Stage A should first isolate regime/hold behavior with fixed
28 DTE, 20% TP, and 30% SL, then refine DTE and exits around survivors.

### Stage B: Intraday Timing Validation

Use UW 15-minute SPY bars for the available recent history.

Requirements:

- admit entries only on bars timestamped 15:45 through before 16:00 ET;
- allow at most one new entry per ET trading date per variant;
- evaluate exits on every bar for which `xsp_session_open(timestamp)` is true;
- do not evaluate exits during the 09:25–09:30 or 17:00–20:15 gaps;
- use trading-session counts, not calendar days, for forced hold limits;
- retain positions over weekends according to actual session availability;
- record entry and exit timestamp, bars held, sessions held, DTE, regime
  features, exit reason, and modeled net return.

Because UW intraday history is shallow, Stage B validates timing and recent
behavior; it cannot replace Stage A's broader regime sample.

### Shared Premium and Cost Stress

The option path remains modeled because UW does not provide historical option
marks or IV surfaces for this period.

Each shortlisted parameter set is rerun under:

- IV seeds: 0.14, 0.18, 0.22, 0.28;
- current paper economics;
- adverse slippage stress at 1.5x and 2x current slippage.

A robust candidate must not depend on a single IV seed or the unstressed cost
case.

## Ranking and Gates

Use a chronological 60/40 train/holdout split for long-history discovery.
Intraday validation uses its own chronological split when sample size permits.

Rank candidates by:

1. positive holdout mean net return;
2. smaller train-to-holdout performance gap;
3. positive median return;
4. adequate trade count;
5. resilience across IV and cost scenarios;
6. MCPT pass on finalists.

Report both the best candidate and the best stable parameter window. Do not
label a single point optimal when neighboring values fail.

A candidate is edge-confirmed only when:

- holdout mean is positive;
- holdout trade count meets the configured minimum;
- MCPT passes at 5%;
- at least two adjacent parameter settings are also positive;
- intraday validation does not reverse the sign;
- the result survives at least three of four IV seeds and 1.5x slippage.

Otherwise, label it `CANDIDATE (least-bad)` and emit `active: false`.

## Current Candidate

Add the current optimizer leader as an inactive paper-soak candidate:

- ID: `opt_dte28_tp20_sl30_gyb`;
- DTE: 28;
- strike: ATM;
- take profit: 20%;
- stop loss: 30%;
- regime: GREEN or YELLOW with fraction at least 0.50;
- yellow bounce not required;
- entry mode: close-window only;
- live state: unchanged;
- active state: false.

This records the hypothesis without consuming active paper capacity until the
new regime/hold study provides stronger evidence.

## Outputs

Write timestamped JSON and Markdown reports under `reports/backtest/`:

- Stage A ranking and stable windows;
- Stage B timing-validation ranking;
- IV and cost sensitivity;
- train/holdout comparison;
- regime and hold attribution;
- recommendation with explicit gate results;
- inactive YAML snippet for human review.

Reports must clearly state data source, bar interval, covered dates, modeled
premium limitations, and whether UW fell back to fixtures.

## Error Handling and Safety

- Load only `UNUSUAL_WHALES_API_KEY` from the TipDrop environment when absent;
  never print or persist its value.
- Cache UW data under `.local/`.
- Fail loudly when an intraday request returns only fixtures or too few bars.
- Never silently interpret daily bars as intraday exits.
- Reject runaway grids before execution.
- Never edit live flags, live variant selection, systemd services, or order
  configuration.

## Testing

Follow test-driven development.

Capability tests:

- entry timestamps outside 15:45–16:00 ET are rejected;
- exactly one close-window entry per trading date is permitted;
- exits are evaluated during GTH, RTH, and Curb;
- exits are blocked during closed gaps and closed weekends;
- forced holds count trading sessions rather than calendar days;
- regime grids generate unique and bounded candidates;
- Stage A and Stage B report their different fidelity levels;
- sensitivity matrices and stability gates are deterministic;
- emitted candidates are always inactive.

Regression tests:

- existing daily backtest and centered optimizer tests stay green;
- session-open behavior remains identical to the live monitor;
- no artifact contains secret values or live-enablement text;
- fixture mode remains offline and deterministic.

## Delivery

1. Premium model produces the implementation plan and identifies engine
   invariants.
2. Grok CLI implements in test-first phases.
3. Run targeted tests, relevant regression tests, and Ruff on touched files.
4. Run the UW discovery and intraday validation.
5. Review results without auto-promoting any candidate.
6. Commit and push to `main`.

