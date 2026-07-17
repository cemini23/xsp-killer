# Debit-spread paper shadow soak

Date: 2026-07-17

## Goal

Accumulate log-only debit-spread economics on every paper Lane A entry
(width=3, matching Stage B research leader) without changing what is traded.

## Done

- Base `config/lane_a_rules.yaml`: `debit_spread_shadow: true`,
  `debit_spread_width_strikes: 3`
- Tests assert prod rules + paper entry attaches shadow on the position
- LIVE_* stays false; no multi-leg in `place_option_order`

## Next

- Let paper-entry timer run; inspect `debit_spread_shadow` on paper JSONL /
  state after entries land
- At N≥20 shadow rows: compare proxy net debit / cost reduction vs naked
- Only then: Agentic multi-leg fill research (funded account)

## Blockers

- None for logging. Historical XSP option tape still unavailable for backtest fills.

## Asks

- Push commits when ready; no operator action beyond normal paper timers.
