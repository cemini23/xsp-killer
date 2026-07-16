# Super Audit v10 Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the UW optimizer statistically honest, align Stage B with runtime timeframes, make session-hold behavior executable, and close every confirmed v10 audit defect without enabling live trading.

**Architecture:** Separate market contexts by timeframe: daily bars produce regime state, completed 1-hour bars produce primary TA, and 15-minute bars provide replay timing. Replace the reused two-way holdout with train/validation/test selection and a shared-sign max-statistic permutation gate. Put exchange-session semantics in one calendar-backed module used by runtime and backtests, and keep all generated candidates inactive and non-promotable while pricing remains synthetic.

**Tech Stack:** Python 3.11+, pandas, NumPy, exchange-calendars, PyYAML, pytest, Ruff.

---

## File map

- Create `xsp_killer/xsp_sessions.py`: shared session key, exchange-calendar session counting, and observed-session helpers.
- Modify `xsp_killer/backtest/intraday.py`: causal daily regime context, completed 1-hour TA, residual exposure metadata, shared sessions.
- Modify `xsp_killer/backtest/engine.py`: consistent end-of-series exit-fill economics.
- Modify `xsp_killer/backtest/optimize.py`: three-way temporal partition and complete split summaries.
- Modify `xsp_killer/backtest/report.py`: family-wise max-statistic MCPT.
- Modify `xsp_killer/backtest/regime_hold.py`: train-only refinement, validation ranking, untouched-test gates, behavioral deduplication, stronger edge gate.
- Modify `xsp_killer/backtest/bars.py`: cache metadata, freshness, and refresh controls.
- Modify `scripts/optimize_regime_hold.py`: strict-UW default, new gates, daily context injection, honest decision table.
- Modify `xsp_killer/lane_a_monitor.py`: runtime `max_hold_sessions`.
- Modify `xsp_killer/robinhood_mcp.py`, `config/rh_mcp.yaml`, and RH docs: token default outside synchronized repo paths.
- Modify `requirements.txt`: add exchange calendar dependency.
- Extend `tests/test_backtest_intraday.py`, `tests/test_backtest_engine.py`, `tests/test_backtest_optimize.py`, `tests/test_backtest_regime_hold.py`, `tests/test_backtest_report.py`, `tests/test_lane_a_monitor.py`, `tests/test_backtest_bars.py`, and `tests/test_robinhood_mcp.py`.

## Task 1: Causal Stage B market contexts

**Files:**
- Modify: `xsp_killer/backtest/intraday.py`
- Modify: `scripts/optimize_regime_hold.py`
- Test: `tests/test_backtest_intraday.py`

- [ ] **Step 1: Write failing anti-lookahead regime tests**

Add tests that pass 60 daily closes plus 15-minute bars into `run_intraday_backtest(..., daily_context=daily)` and assert:

```python
def test_intraday_regime_uses_prior_completed_daily_context(monkeypatch, tmp_path):
    daily = _daily_bars(60, last_close=110.0)
    intraday = _entry_window_bars("2026-07-15", close=100.0)
    seen: list[int] = []

    def spy_regime(closes):
        seen.append(len(closes))
        return _green_regime_frame(closes.index)

    monkeypatch.setattr(intrad, "_regime_series", spy_regime)
    run_intraday_backtest(
        intraday,
        _rules(tmp_path),
        variant_id="causal",
        daily_context=daily,
    )
    assert seen == [60]
```

Add a second test where changing the current session's future close does not change the 15:45 entry decision.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_intraday.py -k "daily_context or future_close" -q
```

Expected: FAIL because `daily_context` is not accepted and 15-minute closes still feed `_regime_series`.

- [ ] **Step 3: Implement causal daily regime alignment**

Add:

```python
def align_completed_daily_regime(
    intraday: pd.DataFrame,
    daily_context: pd.DataFrame,
) -> pd.DataFrame:
    daily = daily_context.sort_index()
    regime = _regime_series(daily["close"].astype(float))
    by_date = {pd.Timestamp(i).date(): row for i, row in regime.iterrows()}
    dates = sorted(by_date)
    rows = []
    for idx in intraday.index:
        civil_date = _bar_ts_et(idx).date()
        eligible = [d for d in dates if d < civil_date]
        rows.append(by_date[eligible[-1]] if eligible else _unknown_regime_row())
    return pd.DataFrame(rows, index=intraday.index)
```

`run_intraday_backtest()` must require `daily_context` for UW Stage B and may derive completed RTH daily closes only for fixture tests. It must never use the current civil day's daily close at 15:45.

- [ ] **Step 4: Write failing completed-1h TA tests**

Assert a future 16:00 15-minute bar cannot alter the TA signal observed at 15:45, and assert the 20-period Bollinger window receives completed hourly bars rather than 15-minute bars.

- [ ] **Step 5: Implement completed 1-hour aggregation**

Create a helper that resamples to 1-hour OHLCV buckets, labels each bucket at its completion time, and maps only bucket timestamps `<= decision_ts` to each 15-minute bar. Use the completed hourly enriched frame for `_ta_signal_at()` and `_ta_entry_ok_at()`. Remove the `i < SMA_SLOW` 15-minute warmup; readiness comes from available daily and hourly contexts.

- [ ] **Step 6: Wire CLI daily bars into every Stage B call**

Pass the already-loaded Stage A daily frame as `daily_context=daily_bars`. If Stage B is requested without Stage A, load strict daily UW context separately.

- [ ] **Step 7: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_intraday.py -q
git add xsp_killer/backtest/intraday.py scripts/optimize_regime_hold.py tests/test_backtest_intraday.py
git commit -m "fix(backtest): align intraday replay with runtime timeframes"
```

## Task 2: Edge gates, residuals, and economics

**Files:**
- Modify: `xsp_killer/backtest/intraday.py`
- Modify: `xsp_killer/backtest/engine.py`
- Modify: `xsp_killer/backtest/regime_hold.py`
- Modify: `scripts/optimize_regime_hold.py`
- Test: `tests/test_backtest_intraday.py`
- Test: `tests/test_backtest_engine.py`
- Test: `tests/test_backtest_regime_hold.py`

- [ ] **Step 1: Write failing zero/thin/residual gate tests**

Add parameterized tests:

```python
@pytest.mark.parametrize(
    ("intraday", "reason"),
    [
        ({"n_trades": 0, "mean_net_pnl_pct": 0.0, "residual_open": 0}, "intraday_sample_below_min"),
        ({"n_trades": 20, "mean_net_pnl_pct": 0.0, "residual_open": 0}, "intraday_mean_not_positive"),
        ({"n_trades": 20, "mean_net_pnl_pct": 0.1, "residual_open": 1}, "intraday_residual_open"),
    ],
)
def test_edge_confirmed_rejects_weak_intraday(intraday, reason):
    ok, why = edge_confirmed(
        _passing_stage_a_row(),
        _passing_sensitivity(),
        intraday,
        min_trades=8,
        min_intraday_trades=20,
    )
    assert (ok, why) == (False, reason)
```

- [ ] **Step 2: Add result-level residual metadata**

Extend `BacktestResult` with `residual_open: int = 0` and `residual_marked_pnl_pct: float | None = None`. At Stage B end, conservatively mark unresolved positions with exit slippage but do not fabricate closed trades. `_summarize_intraday()` must include both fields.

- [ ] **Step 3: Harden `edge_confirmed()`**

Require:

```python
if int(intraday_row.get("n_trades") or 0) < min_intraday_trades:
    return False, "intraday_sample_below_min"
if float(intraday_row.get("mean_net_pnl_pct") or 0.0) <= 0:
    return False, "intraday_mean_not_positive"
if int(intraday_row.get("residual_open") or 0) > 0:
    return False, "intraday_residual_open"
if min(train_mean, validation_mean, test_mean, full_mean) <= 0:
    return False, "cross_split_mean_not_positive"
```

- [ ] **Step 4: Fix daily residual exit economics**

In `engine.py`, compute `exit_fill = exit_fill_premium(mark, econ)`, use it for `net_pnl_pct`, and store the same economics in dollar P&L. Add a parity test where a normal final-bar exit and an end-of-series exit at the same mark have equal percent and dollar P&L.

- [ ] **Step 5: Make synthetic pricing non-promotable**

Add `pricing_fidelity="modeled_bs_lite"` to reports. `edge_confirmed()` may return a research-survivor result, but `promotion_eligible` must remain false unless `pricing_fidelity == "historical_xsp_chain"` and paper confirmation is supplied. Rename the modeled result label from `EDGE-CONFIRMED` to `RESEARCH-SURVIVOR (inactive)`.

- [ ] **Step 6: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_engine.py tests/test_backtest_intraday.py tests/test_backtest_regime_hold.py -q
git add xsp_killer/backtest/engine.py xsp_killer/backtest/intraday.py xsp_killer/backtest/regime_hold.py scripts/optimize_regime_hold.py tests
git commit -m "fix(backtest): harden validation and residual economics"
```

## Task 3: Train/validation/test selection and family-wise MCPT

**Files:**
- Modify: `xsp_killer/backtest/optimize.py`
- Modify: `xsp_killer/backtest/report.py`
- Modify: `xsp_killer/backtest/regime_hold.py`
- Test: `tests/test_backtest_optimize.py`
- Test: `tests/test_backtest_report.py`
- Test: `tests/test_backtest_regime_hold.py`

- [ ] **Step 1: Write failing three-way partition tests**

Define `partition_trades_three_way(trades, bars, train_frac=0.6, validation_frac=0.2)` and assert entries are assigned to contiguous, non-overlapping train/validation/test periods. Assert perturbing test returns does not alter refinement specs.

- [ ] **Step 2: Implement three-way summaries**

Return:

```python
{
    "n_train": ...,
    "n_validation": ...,
    "n_test": ...,
    "train_mean_net_pnl_pct": ...,
    "validation_mean_net_pnl_pct": ...,
    "test_mean_net_pnl_pct": ...,
    "full_mean_net_pnl_pct": ...,
}
```

Coarse/refinement seeds rank on train only. After all cells exist, finalists rank on validation. The untouched test is opened once for final reporting and gates.

- [ ] **Step 3: Write failing max-statistic permutation tests**

Add `familywise_max_stat_mcpt()` tests using null variants and one strongly positive variant. A null family must not produce a high false-positive rate at 5%, and shared date signs must be applied across every variant.

- [ ] **Step 4: Implement family-wise MCPT**

Accept `dict[variant_id, list[tuple[session_key, pnl_pct]]]`. Build a union of session keys, draw one sign per session per permutation, recompute every variant mean, and compare each observed mean against the permutation's maximum mean. Store `familywise_p_value` and `familywise_pass_5pct`.

- [ ] **Step 5: Apply family-wise tests to all qualified finalists**

Do not test only the selected top-K. Preserve the old single-cell MCPT only as `exploratory_mcpt` and label it unadjusted. The edge gate must use `familywise_pass_5pct`.

- [ ] **Step 6: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_optimize.py tests/test_backtest_report.py tests/test_backtest_regime_hold.py -q
git add xsp_killer/backtest/optimize.py xsp_killer/backtest/report.py xsp_killer/backtest/regime_hold.py tests
git commit -m "fix(backtest): add untouched test split and familywise MCPT"
```

## Task 4: Behavioral stability and honest reports

**Files:**
- Modify: `xsp_killer/backtest/regime_hold.py`
- Modify: `scripts/optimize_regime_hold.py`
- Test: `tests/test_backtest_regime_hold.py`

- [ ] **Step 1: Write failing clone-window tests**

Two adjacent parameter cells with identical `(entry_ts, exit_ts, exit_reason)` sequences must count as one behavior and must not form a stable window. Distinct adjacent behaviors with positive train, validation, and test metrics may form one.

- [ ] **Step 2: Add behavior signatures**

Hash the ordered trade tuples with SHA-256. Mark duplicate rows with `behavior_duplicate_of`; exclude duplicates from stable-window graph construction and finalist quotas.

- [ ] **Step 3: Replace the first Markdown ranking table**

The table must include:

```text
variant | hold | n_train | train% | n_val | val% | n_test | test% |
full% | StageB n/mean | residuals | familywise p | status
```

Use `RESEARCH ONLY` when modeled premiums are present. Remove `CANDIDATE` language for negative train/full/test or insufficient Stage B samples.

- [ ] **Step 4: Run report snapshot tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_regime_hold.py -q
git add xsp_killer/backtest/regime_hold.py scripts/optimize_regime_hold.py tests/test_backtest_regime_hold.py
git commit -m "fix(backtest): dedupe behavior and expose split disagreement"
```

## Task 5: Shared calendar-backed session holds

**Files:**
- Create: `xsp_killer/xsp_sessions.py`
- Modify: `xsp_killer/backtest/intraday.py`
- Modify: `xsp_killer/lane_a_monitor.py`
- Modify: `config/lane_a_rules.yaml`
- Modify: `config/lane_a_variants.yaml`
- Modify: `requirements.txt`
- Test: `tests/test_backtest_intraday.py`
- Test: `tests/test_lane_a_monitor.py`

- [ ] **Step 1: Add dependency and failing session tests**

Add `exchange-calendars>=4.5,<5`. Test Sunday-evening-to-Monday mapping, weekends, July 4 closure, Thanksgiving, an early close, and DST weeks.

- [ ] **Step 2: Implement shared session functions**

`xsp_sessions.py` owns:

```python
def exchange_session_key(ts: datetime) -> date: ...
def session_keys_between(start: datetime, end: datetime) -> list[date]: ...
def trading_sessions_held(start: datetime, end: datetime) -> int: ...
```

Use the XNYS calendar as the documented Cboe index-options holiday proxy; preserve XSP GTH date mapping. Fail closed on invalid entry timestamps.

- [ ] **Step 3: Add `max_hold_sessions` to runtime rules**

Parse an optional non-negative integer in `LaneRules.from_yaml()`. In `evaluate_exit_alerts()`, after strategy TP/SL alerts and only while `xsp_session_open(now_et)` is true, emit `hold_cap` once shared `trading_sessions_held()` reaches the cap. Keep precedence `TP/SL > expiry/time-stop > hold-cap`.

- [ ] **Step 4: Make generated YAML executable but inactive**

Emit `exit.max_hold_sessions` now that runtime supports it. Keep `active: false`; do not add any `LIVE_*` text.

- [ ] **Step 5: Add runtime/replay parity test**

Feed the same entry timestamp/current timestamp through runtime `evaluate_exit_alerts()` and Stage B; assert both exit on the same Nth exchange session and not before it.

- [ ] **Step 6: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lane_a_monitor.py tests/test_backtest_intraday.py tests/test_lane_a_variants.py -q
git add requirements.txt xsp_killer/xsp_sessions.py xsp_killer/lane_a_monitor.py xsp_killer/backtest/intraday.py config tests
git commit -m "feat(strategy): share calendar-backed session hold caps"
```

## Task 6: Strict UW defaults and cache freshness

**Files:**
- Modify: `xsp_killer/backtest/bars.py`
- Modify: `scripts/optimize_regime_hold.py`
- Test: `tests/test_backtest_bars.py`
- Test: `tests/test_backtest_intraday.py`

- [ ] **Step 1: Write failing CLI strictness tests**

`--mode uw` without a key must fail nonzero by default. Fixture fallback must require explicit `--allow-fixture-fallback`. Fixture mode remains unchanged.

- [ ] **Step 2: Write failing cache freshness tests**

Create a cached CSV plus metadata older than 24 hours and assert strict loading fetches/raises rather than silently returning it. Assert `--refresh-uw` bypasses a fresh cache.

- [ ] **Step 3: Add sidecar cache metadata**

Write `<cache>.meta.json` with `fetched_at`, `ticker`, `period`, `interval`, `first_bar`, and `last_bar`. `load_uw_bars()` accepts `max_cache_age` and `refresh`; strict optimizer calls default to 24-hour freshness.

- [ ] **Step 4: Make UW CLI strict by default**

Replace the safety semantics with:

```python
strict_uw = args.mode == "uw" and not args.allow_fixture_fallback
```

Keep `--require-uw` as a deprecated compatibility alias for one release. Record `strict_uw`, cache age, and refresh status in JSON/Markdown.

- [ ] **Step 5: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest_bars.py tests/test_backtest_intraday.py -q
git add xsp_killer/backtest/bars.py scripts/optimize_regime_hold.py tests
git commit -m "fix(backtest): make UW strict and cache freshness explicit"
```

## Task 7: Move RH token defaults outside synchronized workspaces

**Files:**
- Modify: `xsp_killer/robinhood_mcp.py`
- Modify: `config/rh_mcp.yaml`
- Modify: `docs/rh_mcp_david.md`
- Modify: `docs/rh_mcp_claudio.md`
- Modify: `docs/rh_mcp_runbook.md`
- Test: `tests/test_robinhood_mcp.py`

- [ ] **Step 1: Write failing platform-default tests**

On Windows, default under `%LOCALAPPDATA%\xsp-killer\robinhood_mcp_token.json`; on POSIX, default under `${XDG_STATE_HOME:-~/.local/state}/xsp-killer/robinhood_mcp_token.json`. Explicit env/config paths still win.

- [ ] **Step 2: Implement safe token path resolution**

Create `default_token_path()` and use it only when neither environment nor config supplies a path. Refuse a resolved token path under the repository root unless an explicit development override is set.

- [ ] **Step 3: Update config and runbooks**

Remove `.local/robinhood_mcp_token.json` as the operational default. Document David and Claudio paths separately without IDs or token values.

- [ ] **Step 4: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_robinhood_mcp.py tests/test_rh_mcp_health.py -q
git add xsp_killer/robinhood_mcp.py config/rh_mcp.yaml docs tests
git commit -m "fix(rh): keep OAuth tokens outside synced repos"
```

## Task 8: Full verification, fresh research run, and ship

**Files:**
- Modify: `briefs/2026-07-16_xsp-killer-super-audit-synthesis-v10.md`
- Create: `briefs/2026-07-16_xsp-killer-super-audit-v10-postfix.md`

- [ ] **Step 1: Install dependencies**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Expected: exit 0.

- [ ] **Step 2: Run Ruff**

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: Run the full test suite with isolated temp paths**

```powershell
$env:TMP="$PWD\.local\tmp"
$env:TEMP="$PWD\.local\tmp"
$env:PYTHONUTF8="1"
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Run a strict UW smoke replay**

```powershell
.\.venv\Scripts\python.exe scripts/optimize_regime_hold.py --mode uw --stage-a --stage-b --coarse-to-fine --mcpt --min-trades 8 --min-intraday-bars 200 --min-intraday-sessions 20
```

Expected: true UW sources only, no fixture fallback, no `EDGE-CONFIRMED`, and a report exposing train/validation/test/full/Stage B disagreement.

- [ ] **Step 5: Run premium post-fix review**

Review only the changed diff for: causal timeframe alignment, untouched-test discipline, family-wise p-values, runtime/replay hold parity, strict-UW behavior, and token path safety. Resolve every concrete P0/P1 finding.

- [ ] **Step 6: Write post-fix brief**

Record commits, test counts, lint result, fresh UW coverage, remaining non-code data limitations, and explicit live NO-GO.

- [ ] **Step 7: Commit and push `main`**

```powershell
git add .
git commit -m "fix(backtest): resolve super-audit v10 findings"
git push origin main
```

- [ ] **Step 8: Verify GitHub CI**

```powershell
gh run list --branch main --limit 3
gh run watch <run-id> --exit-status
```

Expected: CI completes with conclusion `success`.

## Self-review

- Spec coverage: all confirmed v10 P0/P1 findings are mapped to Tasks 1–7; synthetic pricing is converted from an implicit limitation into an explicit non-promotion gate.
- Placeholder scan: no TBD/TODO/“implement later” steps remain.
- Type consistency: `daily_context`, `min_intraday_trades`, `familywise_pass_5pct`, `max_hold_sessions`, and cache freshness names are consistent across tasks.
- Safety: no task enables a variant, writes live RH orders, or changes `LIVE_*` gates.
