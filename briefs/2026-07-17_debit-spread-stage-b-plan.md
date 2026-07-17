# Plan — Stage B debit-spread structure replay (next leverage)

Author: Cursor plan for Grok CLI implement. Date: 2026-07-17.

## 0. Context

- Entry-time UW sweep (`reports/backtest/entry_time_20260716T235322Z.md`): **RESEARCH ONLY**.
  All windows negative; best `am` ≈ −1.3%; EOD close worst. Timing alone does not rescue
  naked ATM long calls under BS-lite.
- Historical XSP fills are a **data gap** (UW/TipDrop = underlying OHLC only; chains are
  live snapshots). Do **not** invent `historical_xsp_chain` fidelity.
- Highest-leverage next experiment: **structure** — call debit spread vs naked, reusing
  existing `debit_spread.py` + dual-leg BS-lite marks. Changes payoff geometry (lower net
  debit, capped upside) so Stage B means can move meaningfully.

## 1. Goal / Done / Non-goals

**Goal:** Replay Stage B under Nagus locks with `structure_mode=naked|debit_spread` so we
can compare mean / win% / early_green side-by-side on the same UW bars.

**Done when:**
1. Intraday replay can mark a 2-leg debit spread (long ATM, short +`width_strikes`×5) via
   existing `build_debit_spread` / `spread_return_pct` + dual `synthesize_call_premium`.
2. CLI runs naked + debit_spread under locked Nagus defaults (or `--structure both`).
3. Report labels `structure_mode`, keeps `pricing_fidelity=modeled_bs_lite`, YAML
   snippets `active: false`, recommendation RESEARCH ONLY unless existing gates pass.
4. Fixture tests green offline; default path remains naked (no behavior change for timers).
5. Local commit when green (**do not push**). No `LIVE_*` flips.

**Non-goals (defer):**
- Historical XSP/SPY option fill tape / `historical_xsp_chain` promotion claims
- Wiring debit spreads into live/paper `lane_a_entry` place path
- New entry-time sweep / expanding Stage A daily grid
- Synthetic bid/ask fill realism without a tape
- Flipping any variant `active: true`

## 2. Design

### Structure modes
| id | legs | mark |
|----|------|------|
| `naked` | long ATM call only (current) | `synthesize_call_premium` → paper fill → `evaluate_exit_alerts` |
| `debit_spread` | long ATM + short ATM+width | dual BS-lite → `build_debit_spread` → TP/SL on **spread return %** |

Defaults: `width_strikes=2` (10 index points), same IV seed as naked (`--iv`).

### Nagus locks for compare (unless CLI overrides)
- `dte_target=30`, `strike_pick=atm_only`, `regime_gate=OFF`
- Volume: run both `vq33` (0.33) and `vall` (off) as small axis **or** fix one cell if budget tight
- TP 30%, late SL 20%, early SL 10% / 90 min
- Entry window: **close** baseline (15:45–16:00) — do not re-sweep am/mid/late this pass
- `max_hold_sessions=5` (fix 5 if grid tight)
- Prefer new `scripts/optimize_structure.py` over bloating `optimize_regime_hold.py`

### Exit math
- Compute `spread_return_pct` each bar from current long/short mids (same scale).
- Feed return into existing TP/SL / early-SL path (thin adapter if `evaluate_exit_alerts`
  expects a single-leg mark — do **not** invent a second strategy engine).
- If a coherent spread cannot be built (short ≥ long mid), skip entry and count `blocked_spread`.

### Report
`reports/backtest/structure_*.{json,md}`:
- Coverage bars/sessions
- Side-by-side table: naked vs debit_spread (n, mean%, win%, early_green_rate, blocked)
- `pricing_fidelity=modeled_bs_lite` always; never claim historical chain
- Inactive YAML with `structure_mode` / `debit_spread_width_strikes` in overrides (documentation only)

## 3. Files

**Edit:**
- `xsp_killer/backtest/option_model.py` — helper to synthesize long+short premiums / path
- `xsp_killer/backtest/intraday.py` — `structure_mode` branch; default `naked`
- `xsp_killer/backtest/variants.py` — knobs: `structure_mode`, `debit_spread_width_strikes`
- Reuse `xsp_killer/debit_spread.py` as-is (`select_short_strike`, `build_debit_spread`,
  `spread_return_pct`)

**Create:**
- `scripts/optimize_structure.py` — fixture + strict UW; `--structure naked|debit_spread|both`
- `tests/test_backtest_structure.py`
- Update this plan Status → DONE when complete

**Do not touch:** systemd, `LIVE_*`, tipdrop secrets, `lane_a_entry` place path, RH MCP writes.

### CLI
```bash
# Offline
PYTHONPATH=/opt/xsp-killer python3 scripts/optimize_structure.py --mode fixture -v

# Strict UW (Hetzner)
export XSP_UW_TIPDROP_ROOT=/opt/tipdrop-scanner
PYTHONPATH=/opt/xsp-killer python3 scripts/optimize_structure.py --mode uw \
  --period 5y --intraday-period 60d --structure both --mcpt --out reports/backtest -v
```

## 4. Tests
1. Naked default unchanged on fixture (smoke parity with existing intraday path)
2. Debit spread entry builds long < short; net debit > 0; TP/SL fire on spread return
3. Incoherent short premium → entry skipped / blocked_spread counted
4. Report contains both modes when `--structure both`; YAML `active: false`; no secrets
5. Existing `tests/test_debit_spread.py` + phased-SL suite still green

## 5. Hard constraints
- `LIVE_ENTRIES` / `LIVE_EXITS` stay false
- No secrets in git/chat
- Never set `pricing_fidelity=historical_xsp_chain`
- Strict UW via tipdrop root; default tipdrop `/opt/tipdrop-scanner` when present
- Match repo style; small diffs; commit locally when green; **do not push**

## 6. Phases for Grok (~1–2h)
1. option_model helper + intraday `structure_mode` + knobs + test 1–3
2. `optimize_structure.py` fixture path + report + test 4
3. UW loader reuse (copy patterns from `optimize_entry_time.py`); operator cmd in Status
4. pytest focused + local commit; mark plan DONE

## 7. Status
- [x] Plan written
- [x] Implemented by Grok (2026-07-17)
- [x] Tests green (`test_backtest_structure`, `test_debit_spread`, `test_nagus_volume_phased_sl`)
- [x] Local commit
- [x] UW operator command documented

### Operator commands

```bash
# Offline fixture (both structures)
PYTHONPATH=/opt/xsp-killer python3 scripts/optimize_structure.py \
  --mode fixture --structure both -v

# Strict UW (Hetzner tipdrop)
export XSP_UW_TIPDROP_ROOT=/opt/tipdrop-scanner
PYTHONPATH=/opt/xsp-killer python3 scripts/optimize_structure.py --mode uw \
  --period 5y --intraday-period 60d --structure both --mcpt \
  --out reports/backtest -v
```

Reports: `reports/backtest/structure_*.{json,md}` — always
`pricing_fidelity=modeled_bs_lite`, YAML `active: false`, RESEARCH ONLY.
