# UW Regime and Hold Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-stage, read-only optimizer that discovers regime and
trading-session hold parameters on long-history UW daily bars, then validates
entry and exit timing on shallow UW 15-minute bars using the live XSP session
calendar.

**Architecture:** Add focused Stage A (`regime_hold.py`) and Stage B
(`intraday.py`) modules rather than growing the existing 650-line optimizer.
Stage A reuses the daily engine with an explicit session-hold cap. Stage B uses
a purpose-built 15-minute replay that delegates session truth to
`xsp_session_open`. A thin CLI runs either stage, stress-tests finalists, and
emits only inactive candidates.

**Tech Stack:** Python 3.11+, pandas, PyYAML, NumPy (MCPT), zoneinfo, pytest,
Ruff, TipDrop `UnusualWhalesProvider`.

---

## File Map

| Action | File | Responsibility |
| --- | --- | --- |
| Create | `xsp_killer/backtest/regime_hold.py` | Stage A grids, daily discovery, sensitivity, stable windows, edge gate |
| Create | `xsp_killer/backtest/intraday.py` | Session-aware 15-minute replay and coverage checks |
| Create | `scripts/optimize_regime_hold.py` | Safe UW loading, orchestration, JSON/Markdown output |
| Create | `tests/test_backtest_regime_hold.py` | Stage A capability and safety tests |
| Create | `tests/test_backtest_intraday.py` | Stage B timing, sessions, coverage, and CLI tests |
| Modify | `xsp_killer/backtest/engine.py` | Backward-compatible `max_hold_sessions` and trade metadata |
| Modify | `xsp_killer/backtest/bars.py` | Strict UW loader and coverage summary; preserve fail-open API |
| Modify | `config/lane_a_variants.yaml` | Add current leader as `active: false` |
| Modify | `tests/test_backtest_engine.py` | Hold-cap regression |
| Modify | `tests/test_lane_a_variants.py` | Inactive-candidate regression |

Do not edit `lane_a_rules.yaml`, systemd units, live variant selection, or any
environment file.

## Fixed Interfaces

```python
# engine.py
@dataclass
class TradeRow:
    # existing required fields unchanged
    sessions_held: int = 0
    bar_interval: str = "1d"

def run_backtest(
    bars: pd.DataFrame,
    rules_path: Path,
    *,
    variant_id: str = "baseline",
    iv_seed: float = 0.18,
    use_bs: bool = True,
    source: str = "fixture",
    force_one_entry_per_day: bool = True,
    max_hold_sessions: int | None = None,
) -> BacktestResult: ...
```

```python
# regime_hold.py
HOLD_SESSIONS_GRID = (1, 2, 3, 5, 10)
IV_SEEDS = (0.14, 0.18, 0.22, 0.28)
SLIPPAGE_MULTS = (1.0, 1.5, 2.0)

def build_stage_a_grid(
    *, coarse: bool = True, allow_large: bool = False, max_grid: int = 240
) -> list[VariantSpec]: ...

def refine_stage_a(
    seed_rows: list[dict[str, Any]],
    *, existing_ids: set[str],
    budget_remaining: int = 120,
) -> list[VariantSpec]: ...

def run_stage_a(
    bars: pd.DataFrame,
    *,
    split_frac: float = 0.6,
    min_trades: int = 8,
    iv_seed: float = 0.18,
    source: str = "fixture",
    coarse_to_fine: bool = True,
    top_k: int = 12,
    run_mcpt: bool = False,
    n_perm: int = 1000,
) -> dict[str, Any]: ...

def run_sensitivity(
    spec: VariantSpec,
    bars: pd.DataFrame,
    *,
    source: str,
    iv_seeds: tuple[float, ...] = IV_SEEDS,
    slippage_mults: tuple[float, ...] = SLIPPAGE_MULTS,
) -> dict[str, Any]: ...

def stable_windows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

def edge_confirmed(
    row: dict[str, Any],
    sensitivity: dict[str, Any],
    intraday_row: dict[str, Any] | None,
    *,
    min_trades: int,
) -> tuple[bool, str]: ...
```

```python
# intraday.py
ENTRY_WINDOW_START = time(15, 45)
ENTRY_WINDOW_END = time(16, 0)

def in_entry_window(ts: datetime) -> bool: ...
def session_date_order(bars: pd.DataFrame) -> list[date]: ...
def trading_sessions_held(
    entry_ts: datetime, now_ts: datetime, session_dates: list[date]
) -> int: ...
def bar_coverage(bars: pd.DataFrame) -> dict[str, Any]: ...
def assert_intraday_coverage(
    bars: pd.DataFrame, *, min_bars: int, min_sessions: int
) -> dict[str, Any]: ...
def run_intraday_backtest(
    bars: pd.DataFrame,
    rules_path: Path,
    *,
    variant_id: str,
    iv_seed: float = 0.18,
    source: str = "fixture",
    max_hold_sessions: int | None = None,
) -> BacktestResult: ...
```

## Task 1: Record the Current Candidate Inactively

**Files:**
- Modify: `tests/test_lane_a_variants.py`
- Modify: `config/lane_a_variants.yaml`

- [ ] **Step 1: Write the failing test**

```python
def test_opt_candidate_is_inactive():
    from xsp_killer.backtest.variants import resolve_variant_specs

    all_specs = resolve_variant_specs(variants="all")
    candidate = next(
        s for s in all_specs if s.variant_id == "opt_dte28_tp20_sl30_gyb"
    )
    assert candidate.active is False
    active_ids = {
        s.variant_id for s in resolve_variant_specs(variants="active")
    }
    assert "opt_dte28_tp20_sl30_gyb" not in active_ids
```

- [ ] **Step 2: Verify RED**

Run:
`.\.venv\Scripts\python.exe -m pytest tests/test_lane_a_variants.py::test_opt_candidate_is_inactive -q`

Expected: `StopIteration` because the candidate is absent.

- [ ] **Step 3: Add the candidate**

```yaml
  opt_dte28_tp20_sl30_gyb:
    active: false
    description: "UW optimizer candidate: 28 DTE ATM, TP20/SL30, GREEN or YELLOW>=0.50"
    overrides:
      logging:
        logic_version: xsp_lane_a_opt_dte28_tp20_sl30_gyb
      entry:
        dte_pick: target
        dte_target: 28
        strike_pick: atm_only
        regime_gate: GREEN_OR_YELLOW_BOUNCE
        regime_yellow_frac_min: 0.50
        regime_yellow_require_bounce: false
        prior_day_spy_positive: false
      ta:
        entry:
          mode: close_window_only
          intraday_enabled: false
          require_vwap_reclaim: false
      exit:
        take_profit_pct: 0.20
        stop_loss_pct: 0.30
        require_upper_bb_for_take_profit: false
        swing_hold: false
        max_hold_dte: 0
```

- [ ] **Step 4: Verify GREEN**

Run the same targeted test; expected: `1 passed`.

- [ ] **Step 5: Commit**

```powershell
git add config/lane_a_variants.yaml tests/test_lane_a_variants.py
git commit -m "test(config): record inactive UW optimizer candidate"
```

## Task 2: Add the Daily Session-Hold Primitive

**Files:**
- Modify: `tests/test_backtest_engine.py`
- Modify: `xsp_killer/backtest/engine.py`

- [ ] **Step 1: Write the failing test**

Create a flat 60-bar path and rules with 90% TP/SL:

```python
def test_max_hold_sessions_forces_exit(tmp_path):
    bars = _flat_series(60)
    rules = _rules(
        tmp_path,
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        dte_target=28,
    )
    result = run_backtest(
        bars,
        rules,
        variant_id="hold3",
        max_hold_sessions=3,
    )
    capped = [t for t in result.trades if t.exit_reason == "hold_cap"]
    assert capped
    assert all(t.bars_held == 3 for t in capped)
    assert all(t.sessions_held == 3 for t in capped)
    assert all(t.bar_interval == "1d" for t in capped)
```

- [ ] **Step 2: Verify RED**

Run the test. Expected: unexpected `max_hold_sessions` keyword.

- [ ] **Step 3: Implement minimally**

Add the defaulted fields and keyword from Fixed Interfaces. In the open-position
loop, after checking strategy alerts and expiry:

```python
held_sessions = i - op.entry_i
if (
    not alerts
    and not force_reason
    and max_hold_sessions is not None
    and held_sessions >= max_hold_sessions
):
    force_reason = "hold_cap"
```

Populate `sessions_held=held_sessions` and `bar_interval="1d"` in emitted
trades, including residual closes.

- [ ] **Step 4: Verify GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_engine.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_optimize.py -q
```

- [ ] **Step 5: Commit**

`git commit -am "feat(backtest): add trading-session hold cap"`

## Task 3: Build the Bounded Stage A Grid

**Files:**
- Create: `tests/test_backtest_regime_hold.py`
- Create: `xsp_killer/backtest/regime_hold.py`

- [ ] **Step 1: Write grid tests**

```python
def test_stage_a_coarse_grid_is_bounded_and_unique():
    specs = build_stage_a_grid()
    ids = [s.variant_id for s in specs]
    assert 1 <= len(specs) <= 240
    assert len(ids) == len(set(ids))
    assert {
        int(s.description.split("hold=")[1].split()[0]) for s in specs
    } == {1, 2, 3, 5, 10}
    assert all(s.overrides["entry"]["strike_pick"] == "atm_only" for s in specs)


def test_stage_a_grid_budget_fails_before_execution():
    with pytest.raises(GridBudgetError):
        build_stage_a_grid(max_grid=10)
```

- [ ] **Step 2: Verify RED**

Expected: module import failure.

- [ ] **Step 3: Implement coarse grid**

Use explicit regime tuples to avoid duplicate GREEN cells:

```python
REGIMES = (
    ("GREEN", None, None, "green"),
    *tuple(
        ("GREEN_OR_YELLOW_BOUNCE", frac, bounce, f"gyb{int(frac*100)}b{int(bounce)}")
        for frac in (0.40, 0.50, 0.60, 0.75)
        for bounce in (False, True)
    ),
)
```

Coarse search fixes DTE 28, TP 20%, SL 30%, then varies 9 regimes × two
prior-day modes × five holds = 90 cells. Store the hold in a
`StageASpec(spec: VariantSpec, max_hold_sessions: int)` dataclass; do not add an
unknown live YAML key.

- [ ] **Step 4: Verify GREEN**

Run `tests/test_backtest_regime_hold.py -k grid`.

- [ ] **Step 5: Commit**

```powershell
git add xsp_killer/backtest/regime_hold.py tests/test_backtest_regime_hold.py
git commit -m "feat(backtest): add bounded regime hold grid"
```

## Task 4: Run Stage A and Refine Survivors

**Files:**
- Modify: `tests/test_backtest_regime_hold.py`
- Modify: `xsp_killer/backtest/regime_hold.py`

- [ ] **Step 1: Add failing discovery test**

```python
def test_stage_a_ranks_holdout_and_labels_fidelity():
    payload = run_stage_a(
        load_fixture_daily(),
        min_trades=1,
        coarse_to_fine=False,
        source="fixture",
    )
    assert payload["fidelity"] == "daily_close_proxy"
    assert "exits checked once per daily bar" in payload["disclaimer"]
    means = [r["holdout_mean_net_pnl_pct"] for r in payload["ranking"]]
    assert means == sorted(means, reverse=True)
```

- [ ] **Step 2: Verify RED**

Expected: `run_stage_a` absent.

- [ ] **Step 3: Implement Stage A**

For each `StageASpec`, write merged rules with `rules_path_for_spec`, call
Call `run_backtest` with the cell's bars, rules path, variant ID, IV seed,
source, and `max_hold_sessions=cell.max_hold_sessions`. Partition with
`partition_trades_by_split`, summarize train/holdout/full, and sort by holdout
mean then stability gap and trade count.

- [ ] **Step 4: Add failing refinement test**

Assert refinement only uses DTE `{21,28,35}`, TP `{0.10,0.15,0.20,0.25}`, SL
`{0.20,0.30,0.40}`, preserves each survivor's regime and hold, creates unique
IDs, and respects `budget_remaining`.

- [ ] **Step 5: Implement refinement and verify**

Refine only the top `top_k` coarse rows. Reject the combined grid before
execution if it exceeds its budget.

- [ ] **Step 6: Commit**

`git commit -am "feat(backtest): run and refine Stage A discovery"`

## Task 5: Add Sensitivity and Stable-Window Gates

**Files:**
- Modify: `tests/test_backtest_regime_hold.py`
- Modify: `xsp_killer/backtest/regime_hold.py`

- [ ] **Step 1: Write failing sensitivity test**

```python
def test_sensitivity_is_deterministic_and_complete():
    result = run_sensitivity(candidate, load_fixture_daily(), source="fixture")
    assert result == run_sensitivity(
        candidate, load_fixture_daily(), source="fixture"
    )
    assert len(result["cells"]) == 12
    assert result["iv_seeds"] == [0.14, 0.18, 0.22, 0.28]
    assert result["slippage_mults"] == [1.0, 1.5, 2.0]
```

- [ ] **Step 2: Verify RED**

Expected: function absent.

- [ ] **Step 3: Implement sensitivity**

For every IV/slippage pair, scale all three slippage fields from the base
`paper_economics` block, write temporary merged rules, and rerun. Record sample
size, mean, median, and sign. Do not mutate global config.

- [ ] **Step 4: Write failing stable-window and edge-gate tests**

Test that one isolated positive cell is not stable, two adjacent positive hold
or threshold cells are stable, and edge confirmation requires:

- positive holdout mean;
- sufficient holdout sample;
- MCPT pass;
- an adjacent positive cell;
- non-negative intraday validation;
- at least three positive IV seeds;
- positive 1.5× slippage result.

- [ ] **Step 5: Implement and verify**

`recommended_regime_hold_yaml` always emits `active: false`, regardless of gate
status.

- [ ] **Step 6: Commit**

`git commit -am "feat(backtest): add robustness and stable-window gates"`

## Task 6: Implement Entry Timing and Session Counting

**Files:**
- Create: `tests/test_backtest_intraday.py`
- Create: `xsp_killer/backtest/intraday.py`

- [ ] **Step 1: Write failing entry-window test**

```python
def test_entry_window_is_inclusive_1545_exclusive_1600():
    assert in_entry_window(et(2024, 6, 13, 15, 45))
    assert in_entry_window(et(2024, 6, 13, 15, 59))
    assert not in_entry_window(et(2024, 6, 13, 15, 30))
    assert not in_entry_window(et(2024, 6, 13, 16, 0))
```

- [ ] **Step 2: Verify RED, then implement**

`in_entry_window` converts to ET, rejects weekends, checks
`ENTRY_WINDOW_START <= time < ENTRY_WINDOW_END`, and requires
`xsp_session_open(ts)`.

- [ ] **Step 3: Write failing session-order test**

Use bars spanning Friday, closed Saturday afternoon, Sunday evening, and
Monday. Assert only dates with at least one session-open bar appear and that a
Friday entry reaches hold count one on the next ordered trading date—not merely
after one calendar day.

- [ ] **Step 4: Implement and verify**

Build the ordered distinct ET dates from bars for which `xsp_session_open` is
true. Count index distance; do not reimplement market hours.

- [ ] **Step 5: Commit**

```powershell
git add xsp_killer/backtest/intraday.py tests/test_backtest_intraday.py
git commit -m "feat(backtest): add XSP entry window and session counting"
```

## Task 7: Implement Session-Aware 15-Minute Replay

**Files:**
- Modify: `tests/test_backtest_intraday.py`
- Modify: `xsp_killer/backtest/intraday.py`

- [ ] **Step 1: Write failing one-entry-per-date test**

Create synthetic bars with two close-window timestamps on one ET date; assert
one entry maximum.

- [ ] **Step 2: Write failing session-parity tests**

Parameterize timestamps for GTH, RTH, Curb, 09:25–09:30 gap, 17:00–20:15 gap,
Saturday tail, Saturday afternoon, Sunday daytime, and Sunday reopen. Assert
the replay's exit eligibility equals `xsp_session_open(ts)` exactly.

- [ ] **Step 3: Write failing hold-cap test**

Enter Friday 15:45. With `max_hold_sessions=1`, a stop-free position force
closes on the next observed session date, with `exit_reason="hold_cap"` and
`sessions_held=1`.

- [ ] **Step 4: Implement replay**

Iterate chronologically:

1. Convert index to ET.
2. Mark each open position using `synthesize_call_premium`.
3. Call `evaluate_exit_alerts(pos, lane_rules, now_et=ts, ta_signal=ta_sig)`;
   rely on its session gate.
4. Apply the trading-session hold cap only when `xsp_session_open(ts)` is true.
5. Open at most one entry per ET date and only in `[15:45,16:00)`.
6. Reuse `_regime_series` and `regime_gate_allows`.
7. Emit `TradeRow` with `bar_interval="15m"` and the integer returned by
   `trading_sessions_held` in `sessions_held`.

- [ ] **Step 5: Verify all Stage B tests**

`.\.venv\Scripts\python.exe -m pytest tests/test_backtest_intraday.py -q`

- [ ] **Step 6: Commit**

`git commit -am "feat(backtest): add session-aware intraday replay"`

## Task 8: Add Coverage Honesty and Strict UW Loading

**Files:**
- Modify: `tests/test_backtest_intraday.py`
- Modify: `xsp_killer/backtest/bars.py`
- Modify: `xsp_killer/backtest/intraday.py`

- [ ] **Step 1: Write failing coverage tests**

```python
def test_fixture_coverage_reports_rth_only():
    coverage = bar_coverage(load_fixture_intraday())
    assert coverage["n_bars"] > 0
    assert coverage["n_sessions"] >= 1
    assert coverage["has_overnight_bars"] is False
    assert coverage["session_phases_observed"] == ["RTH"]
```

- [ ] **Step 2: Write failing strict-loader tests**

With no key/provider, strict loading raises `FixtureFallbackError`; a 10-bar
frame raises `InsufficientBarsError` for `min_bars=200`. Existing `load_bars`
continues to fail open.

- [ ] **Step 3: Implement minimally**

Add exceptions and `load_uw_bars_strict` without changing `load_bars`. Coverage
reports start/end, bar/session counts, interval, overnight presence, and
observed GTH/RTH/Curb phases. Never invent absent phases.

- [ ] **Step 4: Verify regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_intraday.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_engine.py -q
```

- [ ] **Step 5: Commit**

`git commit -am "feat(backtest): add strict UW intraday coverage checks"`

## Task 9: Add the Orchestration CLI and Reports

**Files:**
- Modify: `tests/test_backtest_intraday.py`
- Create: `scripts/optimize_regime_hold.py`

- [ ] **Step 1: Write failing fixture CLI test**

Run with `--mode fixture --stage-a --stage-b`. Assert timestamped JSON and
Markdown, both fidelity labels, coverage data, an inactive YAML snippet, and no
secret key name or live-enablement strings.

- [ ] **Step 2: Write failing strict UW test**

Run `--mode uw --require-uw` with an empty key. Assert nonzero exit and no
fixture report.

- [ ] **Step 3: Implement CLI**

Arguments:

```text
--mode fixture|uw
--stage-a
--stage-b
--period 5y
--intraday-period 60d
--split-frac 0.6
--min-trades 8
--top-k 12
--mcpt
--mcpt-perm 1000
--coarse-to-fine
--allow-large
--require-uw
--min-intraday-bars 200
--min-intraday-sessions 20
--out reports/backtest
-v
```

Load only `UNUSUAL_WHALES_API_KEY` from TipDrop `.env` if absent and log only
whether loading succeeded. Stage A loads daily bars; Stage B uses strict 15m
loading in UW mode. Reports include source, exact dates, interval, observed
session phases, train/holdout, sensitivity, stable windows, MCPT, recommendation
status, and inactive YAML.

- [ ] **Step 4: Verify fixture and strict-failure tests**

Expected: fixture exits 0; UW without key exits nonzero.

- [ ] **Step 5: Commit**

```powershell
git add scripts/optimize_regime_hold.py tests/test_backtest_intraday.py
git commit -m "feat(backtest): add regime hold optimizer CLI"
```

## Task 10: Verify, Run UW, Commit, and Push

- [ ] **Step 1: Run targeted tests**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_backtest_regime_hold.py `
  tests/test_backtest_intraday.py `
  tests/test_backtest_engine.py `
  tests/test_backtest_optimize.py `
  tests/test_lane_a_variants.py -q
```

- [ ] **Step 2: Run Ruff**

```powershell
.\.venv\Scripts\python.exe -m ruff check `
  xsp_killer/backtest/regime_hold.py `
  xsp_killer/backtest/intraday.py `
  xsp_killer/backtest/engine.py `
  xsp_killer/backtest/bars.py `
  scripts/optimize_regime_hold.py `
  tests/test_backtest_regime_hold.py `
  tests/test_backtest_intraday.py
```

- [ ] **Step 3: Run real Stage A**

Load the key without printing it, set `XSP_UW_TIPDROP_ROOT`, then:

```powershell
.\.venv\Scripts\python.exe scripts/optimize_regime_hold.py `
  --mode uw --require-uw --stage-a --period 5y `
  --coarse-to-fine --split-frac 0.6 --min-trades 8 `
  --mcpt --mcpt-perm 1000 -v
```

- [ ] **Step 4: Run real Stage B**

```powershell
.\.venv\Scripts\python.exe scripts/optimize_regime_hold.py `
  --mode uw --require-uw --stage-b --intraday-period 60d `
  --min-intraday-bars 200 --min-intraday-sessions 20 -v
```

If UW provides only RTH bars, report that limitation. If fewer than the
configured floors are returned, preserve the failure; do not weaken the floor
merely to obtain a result.

- [ ] **Step 5: Review outputs**

Do not call a result optimal unless it clears all edge gates and has an
adjacent positive window. Never auto-activate its YAML.

- [ ] **Step 6: Commit remaining report-safe code and push**

```powershell
git status -sb
git add config/lane_a_variants.yaml scripts/optimize_regime_hold.py `
  tests/test_backtest_engine.py tests/test_backtest_intraday.py `
  tests/test_backtest_regime_hold.py tests/test_lane_a_variants.py `
  xsp_killer/backtest/bars.py xsp_killer/backtest/engine.py `
  xsp_killer/backtest/intraday.py xsp_killer/backtest/regime_hold.py
git commit -m "feat(backtest): optimize UW regimes and trading-session holds"
git push origin HEAD
```

## Completion Criteria

- Entries are accepted only from 15:45 through before 16:00 ET.
- Stage B exit eligibility is exactly the live `xsp_session_open` result.
- Holds use observed trading-session dates, not calendar-day subtraction.
- Stage A reports daily-close fidelity; Stage B reports actual observed phases.
- Regime and hold grids are bounded before execution.
- Sensitivity covers four IV seeds and three slippage levels.
- Finalists require positive holdout, MCPT, adjacent positives, intraday
  non-reversal, and stress resilience.
- Every emitted/configured candidate remains `active: false`.
- UW strict mode never silently substitutes fixtures.
- Tests and Ruff pass; changes are committed and pushed to `main`.

