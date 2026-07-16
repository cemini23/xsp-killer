# Plan — UW-Driven Centered Parameter Search for Lane A (28 DTE ATM cluster)

Author: Opus plan for Grok CLI implement. Date: 2026-07-16.

## 0. Context snapshot

- Today's UW backtest (`lane_a_bt_20260716T162213Z`) = all variants negative mean, MCPT pass=0. Least-bad = 28 DTE ATM trio.
- Dip-swing grid pruned (`active:false`). Legacy `sweep.py` still centers micro-sweeps on `DIP_SWING_BASE_OVERRIDES` — wrong base.
- Engine `_pick_strike`: `atm_only` and `cheapest_near_atm` are identical offline (no chain) — **exclude strike axis**.

## 1. Goal / Done / Non-goals

**Goal:** Bounded factorial search around **28 DTE ATM** on UW 2y SPY daily, train/holdout split, MCPT on survivors only; ranked report + human-apply YAML snippet (`active: false`).

**Done when:**
- `python scripts/optimize_lane_a.py --mode fixture` offline → `reports/backtest/optimize_*.{json,md}`
- `--mode uw` ≤ ~80 combos; MCPT on top-K only
- Tests green; no LIVE flips; no secrets

**Non-goals:** No LIVE_*; no secrets; relative ranker only; no new framework.

## 2. Design

### Files
**Create:** `xsp_killer/backtest/optimize.py`, `scripts/optimize_lane_a.py`, `tests/test_backtest_optimize.py`  
**Edit:** `xsp_killer/backtest/sweep.py` — add `BASE_28DTE_ATM_OVERRIDES`; point legacy micro-sweep at it  
**Do NOT touch:** `engine.py`, `bars.py`, `report.py`, `config/lane_a_variants.yaml`, LIVE/systemd

### Base (`BASE_28DTE_ATM_OVERRIDES`)
- entry: dte_target 28, atm_only, regime GREEN, prior_day false
- ta.entry: close_window_only
- exit: TP 0.10, SL 0.20, require_upper_bb_for_take_profit false, swing off

### Grid (72 ≤ 80)
| axis | values |
|---|---|
| dte_target | 21, 28, 35 |
| take_profit_pct | 0.08, 0.10, 0.15, 0.20 |
| stop_loss_pct | 0.15, 0.20, 0.30 |
| regime_gate | GREEN; GREEN_OR_YELLOW_BOUNCE (frac 0.50, bounce false) |

Budget guard: error if grid > 80 without `--allow-large`. Optional `--refine` ±neighbors.

### Split / rank / MCPT
- Train = first 60% of bar date-range by entry_ts; holdout = last 40%
- Rank by holdout_mean_net_pnl_pct; top-K=8 get MCPT (n_perm=1000)
- Recommend promote-shape only if holdout_mean>0 AND mcpt_pass AND n≥min_trades; else least-bad labeled `active:false` + CANDIDATE

### UW key
- Load only `UNUSUAL_WHALES_API_KEY` from tipdrop `.env` if unset; never log value
- Reuse `load_bars(mode=uw)` + `.local/uw_cache/`; fail-open loud WARN

## 3. Tests (`tests/test_backtest_optimize.py`)
1. base is 28dte atm bb-off
2. grid size 72, unique ids, no strike
3. partition trades by split
4. run_optimize fixture + MCPT on ≤K
5. budget guard
6. recommended yaml active:false + no LIVE/secrets
7. CLI fixture offline
8. CLI uw no-key fallback
9. no secrets in artifacts

## 4. Operator CLI
```bash
python scripts/optimize_lane_a.py --mode fixture -v
python scripts/optimize_lane_a.py --mode uw --period 2y --split-frac 0.6 \
  --min-trades 8 --top-k 8 --mcpt --mcpt-perm 1000 -v
python scripts/optimize_lane_a.py --mode uw --period 2y --refine --mcpt -v
```

## 5. Phases (~1–2h Grok)
1. Base + grid builder + tests 1–2,5
2. Split runner + tests 3–4
3. Report + YAML emitter + tests 6,9
4. CLI + env safety + tests 7–8
5. pytest + lint + commit + push (do NOT auto-apply variant to config)

Human pastes snippet only if edge-confirmed after paper soak.
