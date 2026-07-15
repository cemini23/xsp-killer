# XSP Lane A — Mentor Playbook v2

## Entry (automated at close)
- **When:** 15:45–16:00 ET, Mon–Fri
- **DTE:** ≥14 days (2 weeks minimum); **baseline `dte_max: 60`** for overnight prod
- **Strike:** Cheapest premium among near-ATM strikes (±5 SPX points)
- **Regime:** GREEN required (macro_regime fallback when Redis intel absent)
- **No BB gate** at entry — mentor: hardest part is timing; automate buy at close

## Exit (anytime XSP session is open)
- **Session gate only:** Cboe XSP GTH (20:15–09:25), RTH (09:30–16:15), or Curb (16:15–17:00) ET
- **No clock sell / no-sell window** — if TP/SL/BB conditions hit while tradeable, sell
- **Stop loss:** −20% from entry mid
- **Take profit:** +20% only when upper Bollinger band touched or rejection signal
- **No daily morning time_stop** — exit on conditions, not the clock
- **Patience:** If +20% but no upper BB touch → hold (wait for real run)
- **Inherited by all shadow variants** via `lane_a_rules.yaml` deep-merge

## Sleeve map

| Sleeve | DTE window | Config | Notes |
|--------|------------|--------|-------|
| **Lane A** (overnight) | 14–60 | `lane_a_rules.yaml` | Prod baseline; do not raise `dte_max` here |
| **Lane A⅔** (mid-tenor) | ~70–90 (target **80**) | variant `v2_mid_tenor_80dte_atm` | Mentor 9/30-class monthly–quarterly; **override-only** `dte_max: 90` |
| **Lane B** (LEAPS core) | ≥180 | Lane B rules | Long-dated core / swing hold |

Far-DTE OTM operator soak (`v2_dip_swing_55dte_otm`) uses variant **`dte_max: 65`** so 55 vs 60 targets can pick distinct Fridays without touching overnight baseline.

## Paper economics
- Slippage: 1.5% of premium
- Commission: $0.65/contract (entry + exit)

## Logic version
`xsp_lane_a_v2`
