# Plan — paper soak hygiene (2026-07-30)

**Status:** DONE (Cursor)

## Problem
Paper soak dollars were biased: legacy morning `time_stop` dominated the epoch, `premium_scale` 10× inflated headlines, and `close_open_paper_positions` treated `mark_price=0.0` as missing.

## Changes
1. **Code:** preserve zero marks on operator paper close; dual-log 1× as primary in paper brief + scoreboard guidance.
2. **Ops:** `reset-soak` archives contaminated epoch and starts a fresh PnL/scoreboard epoch (post–morning-cut rules).
3. **Ops:** `lane_a_risk_reset` clears consecutive-loss halt so new epoch can enter when regime allows.

## Hard stops
No `LIVE_*` flips. State/scoreboard files remain gitignored; only code + this plan commit.
