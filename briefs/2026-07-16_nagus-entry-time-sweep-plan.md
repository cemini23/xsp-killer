# Plan — Nagus entry-time sweep (find edge beyond EOD)

Author: Cursor plan for Grok CLI implement. Date: 2026-07-16.

## 0. Context

- Full UW history works (`timeframe` + paging). Latest regime/hold + volume-primary run:
  `reports/backtest/regime_hold_20260716T233544Z.md` → **RESEARCH ONLY**.
- Nagus: quiet/slow volume days matter more than regime; 10% SL in first ~90 min then widen;
  ~30 DTE ATM; TP 20–50%. Best personal results were **entries all day**, not proven EOD.
- We have only stress-tested **15:45–16:00 ET** close-window entries. That is the highest-leverage gap.

## 1. Goal / Done / Non-goals

**Goal:** Add a Stage B **entry-time bucket sweep** on strict UW 15m bars, reusing volume gate +
time-phased early SL, so we can see whether any intraday window shows a research-survivor signal
that EOD does not.

**Done when:**
1. Entry windows are configurable (not hard-coded only to 15:45–16:00).
2. CLI can run a small bucket sweep (morning / midday / late / close) under Nagus defaults.
3. Report ranks buckets + variants; YAML snippets stay `active: false`.
4. Early-green telemetry (green within 90 min?) logged on Stage B trades (analysis only, not a hard gate yet).
5. Fixture tests green offline; strict UW path unchanged defaults for existing timers.
6. Local commit when green (do **not** push unless asked). No `LIVE_*` flips.

**Non-goals (Phase 2 — document only, do not implement this pass):**
- Historical XSP chain fill pricing
- Hedged / debit-spread structures
- Activating variants or live gates
- Expanding Stage A daily grid further

## 2. Design

### Entry windows (ET)
| id | window | intent |
|----|--------|--------|
| `close` | 15:45–16:00 | current baseline (EOD) |
| `late` | 14:00–15:00 | afternoon |
| `mid` | 11:30–13:00 | midday |
| `am` | 09:45–11:00 | morning (skip open auction chaos) |

Keep one entry per civil date max (existing rule). Window must still require `in_entry_window`.

### Nagus defaults for this sweep (lock unless CLI overrides)
- `dte_target=30`, `strike_pick=atm_only`
- `regime_gate=OFF` (volume primary)
- `volume_gate_max_pctile=0.33` (quiet third) — also run `None` as control cell
- `take_profit_pct=0.30`
- `stop_loss_pct=0.20` (late), `stop_loss_pct_early=0.10`, `stop_loss_early_minutes=90`
- `prior_day_spy_positive=false`
- `max_hold_sessions` ∈ {3, 5} for a tiny hold axis (optional; if budget tight, fix hold=5)

### Files
**Edit:**
- `xsp_killer/backtest/intraday.py` — generalize `in_entry_window(now, start, end)`; pass window from knobs/rules
- `xsp_killer/backtest/variants.py` — knobs: `entry_window_start_et`, `entry_window_end_et` (or window id)
- `xsp_killer/backtest/regime_hold.py` — optional: helper to build entry-time StageASpec list (or keep in script)
- `scripts/optimize_regime_hold.py` **or new** `scripts/optimize_entry_time.py` — prefer **new script** to avoid breaking regime/hold CLI

**Create:**
- `scripts/optimize_entry_time.py`
- `tests/test_backtest_entry_time.py`
- Update this plan Status → DONE when complete

**Do not touch:** systemd units, `LIVE_*`, tipdrop secrets, paper soak timers.

### CLI
```bash
# Offline
python3 scripts/optimize_entry_time.py --mode fixture -v

# Strict UW (uses tipdrop key via existing loader)
python3 scripts/optimize_entry_time.py --mode uw --period 5y --intraday-period 60d \
  --mcpt --out reports/backtest -v
```

Flags:
- `--windows close,late,mid,am` (default all four)
- `--volume-pctile 0.33` and/or `--volume-pctile none` (control)
- Reuse strict UW / refresh / cache behavior from `optimize_regime_hold.py` (copy patterns, don't regress)

### Report
`reports/backtest/entry_time_*.{json,md}` with:
- Coverage (bars/sessions)
- Per-window leader table: n_train/val/test, means, Stage B mean/n, early_green_rate, familywise p
- Recommendation: RESEARCH ONLY unless existing `edge_confirmed` + `promotion_eligible` gates pass (they should not flip live)
- Inactive YAML snippet including `entry.window_start_et` / `window_end_et`

### Early-green telemetry
On each closed Stage B trade, if any bar within 90 minutes of entry has `ret_pct > 0` before exit → `early_green=True`. Aggregate `early_green_rate` per cell. **Do not gate** on it this pass.

## 3. Tests
1. `in_entry_window` respects custom start/end; close window unchanged default
2. Fixture entry-time run produces one report; all windows present
3. Volume gate still blocks loud prior days inside a non-close window
4. Early SL 10% still fires inside 90 min (reuse / don't break existing phased-SL tests)
5. YAML snippet `active: false`; no secrets in artifact
6. Grid budget guard if combo count exceeds small default (e.g. 24)

## 4. Hard constraints
- `LIVE_ENTRIES` / `LIVE_EXITS` stay false
- No secrets in git
- Strict UW by default for `--mode uw` (existing pattern)
- Match repo style; prefer small diffs
- Commit locally when tests pass; **do not push**

## 5. Phases for Grok (~1–2h)
1. Generalize entry window + knobs + tests 1
2. `optimize_entry_time.py` fixture path + report + tests 2,5,6
3. Wire early-green telemetry + test assert field present
4. UW path smoke (reuse loaders); document operator command in plan Status
5. pytest focused + ruff on touched files + local commit

## 6. Status
- [x] Plan written
- [x] Implemented by Grok
- [x] Tests green
- [ ] Local commit
- [x] Fresh UW entry-time report path documented

### Operator commands (post-implementation)

```bash
# Offline fixture smoke
PYTHONPATH=/opt/xsp-killer python3 scripts/optimize_entry_time.py --mode fixture -v

# Strict UW entry-time sweep (uses tipdrop key via existing loader; no LIVE_* flips)
PYTHONPATH=/opt/xsp-killer python3 scripts/optimize_entry_time.py --mode uw \
  --period 5y --intraday-period 60d --mcpt --out reports/backtest -v

# Focused tests
PYTHONPATH=/opt/xsp-killer python3 -m pytest \
  tests/test_backtest_entry_time.py tests/test_nagus_volume_phased_sl.py -q
```

Reports: `reports/backtest/entry_time_*.{json,md}` (YAML snippet always `active: false`).
