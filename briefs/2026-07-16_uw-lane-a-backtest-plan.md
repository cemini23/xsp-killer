# UW-driven Lane A XSP Backtest — Implementation Plan (2026-07-16)

Author: Claudio recon for Grok CLI. Target: ship a usable CLI **today**, before
the operator installs `UNUSUAL_WHALES_API_KEY` (~11:30 ET), then light up live
UW data when the key lands. Scope: a few hours of Grok work, not a platform.

---

## Status (2026-07-16) — DONE (TODAY MVP Phases A+B+C)

**Shipped offline-first:**
- Package `xsp_killer/backtest/` — `bars`, `option_model`, `engine`, `variants`,
  `sweep`, `report` (MCPT-lite sign-flip ported into `report.mcpt`).
- CLI: `python3 scripts/backtest_lane_a.py --mode fixture` (also `--mode uw`
  fail-open → fixture, `--variants active`, `--sweep tp,dte`, `--mcpt`, `--out`).
- Fixtures: `tests/fixtures/backtest/spy_daily.csv` + `spy_15m.csv`.
- Tests: `tests/test_backtest_engine.py` (14 green offline; TP/SL/time_stop,
  determinism, real `evaluate_exit_alerts` + `paper_economics`, UW fail-open,
  MCPT n&lt;5).
- Cache path: `.local/uw_cache/` (gitignored via `.local/`).
- **No** `LIVE_ENTRIES` / `LIVE_EXITS` / any `LIVE_*` flips. No secrets in tree.

Operator light-up after key paste:
```bash
python3 scripts/backtest_lane_a.py --mode uw --start 2024-01-01 \
    --variants active --sweep tp,dte --mcpt --out reports/backtest/
```

### Nagus alignment (wiki pushed 2026-07-16)

Source: `@concepts/nagus-ops-control-plane.md` (OSINT wiki) + laptop MVP
`scripts/xsp_ops/` (sensor→parse→land→enqueue→triage→packet→scale).

| Layer | Nagus / xsp_ops | This backtest |
|-------|-----------------|---------------|
| Role | Ops **control plane** (live state moves) | Strategy **ranker** (historical SPY→modeled premiums) |
| Sensors | Macro Charts RSS | UW OHLC (or fixture) |
| Brain / queue | `.local/ops/xsp/{state,queue,packets}/` | `reports/backtest/*.json\|md` + `.local/uw_cache/` |
| Token discipline | One thin CLI role per job | One CLI; no LLM in the loop |
| Promote | Human copies packets → `briefs/xsp-*` | Human uses rankings to prioritize soak variants |

**Next (optional, not blocking UW key today):** treat a backtest run as another
**sensor** into Nagus — write a summary JSON under `.local/ops/xsp/state/` or
enqueue a triage packet when a variant window looks healthy (MCPT pass). Do
**not** auto-promote briefs or flip `LIVE_*`. Full `xsp_ops` loop stays on the
laptop OSINT tree unless we deliberately port it to `/opt/xsp-killer`.

---

## Goal / Done / Non-goals

**Goal.** Cut paper-soak time by *ranking* which Lane A variants and parameter
windows look profitable, using historical SPY OHLC (via TipDrop
`UnusualWhalesProvider`) replayed through the **existing** Lane A entry/exit
decision functions. Output: (a) a ranked variant table, (b) recommended
"healthy" parameter windows per axis, (c) optional MCPT-lite p-values so we
don't chase noise.

**Done when:**
- `python3 scripts/backtest_lane_a.py --mode fixture` runs fully offline (no key,
  no network) and prints a ranked table + writes `reports/backtest/*.json` +
  `*.md`. Green in `pytest`.
- Same CLI with `--mode uw` fetches + caches SPY daily/intraday OHLC and reruns
  the identical engine.
- `--mcpt` appends a permutation p-value column.
- Reuses `evaluate_exit_alerts`, `lane_a_ta`, `paper_economics`, and the variant
  resolver — no second strategy implementation.

**Non-goals (hard):**
- Does **not** enable `LIVE_ENTRIES` / `LIVE_EXITS` / any `LIVE_*`. Read-only.
- Does **not** replace the paper soak for LIVE promotion (see disclaimer).
- No secrets in git. No historical *option* fills claimed as truth.
- Not a walk-forward optimizer / RL trainer. EMAgnet is a *reference only* — we
  borrow only the idea of scanning a small bounded parameter region.

---

## Fidelity model (be honest about what UW can and cannot give us)

TipDrop `UnusualWhalesProvider` (`/opt/tipdrop-scanner/data/fetcher.py`):

| Method | Returns | History depth | Usable for backtest? |
|---|---|---|---|
| `get_history(ticker, period, "1d")` | **underlying** daily OHLC | UW caps 1500 bars ⇒ ~6 yrs daily | **Yes** — high fidelity underlying path |
| `get_intraday(ticker, interval, period)` | underlying intraday OHLC | 1500 bars ⇒ ~4 sessions @1m, ~38 sessions @15m | Yes but **shallow** |
| `get_flow_alerts`, `get_iv_rank_uw`, gex-levels, net-prem | recent-window snapshots | **no deep history** | **No** — forward-only overlays |

**Hard truths that shape the design:**

1. **No historical option chains, option marks, or IV surface from UW.** We only
   get the *underlying* price path. Therefore the option premium path **must be
   synthesized** from SPY OHLC. This is a model, not a fill tape.
2. **SPY → XSP proxy.** XSP ≈ SPX/10 ≈ SPY level; a real XSP call premium ≈ the
   SPY call premium (~1×). Existing code already assumes this
   (`spy_quote.xsp_strike_to_spy_chain_strike`, `paper_economics.premium_scale`).
   % TP/SL are scale-invariant, so ranking is robust to the 1× vs 10× scaling.
3. **Premium synthesis = Black-Scholes-lite** driven by the underlying path plus
   an assumed IV (seed from a constant, later refine with UW `get_iv_rank_uw`
   *for forward runs only*). Delta/gamma/theta over the path is what actually
   drives TP/SL hits — that is the signal we can model with medium fidelity.
   Fall back to the existing `lane_a_entry.estimate_fallback_premium` (already a
   strike/DTE-aware paper premium) if BS-lite is over-scoped for today.
4. **Intraday-entry variants (DIP_BOUNCE / bb_bounce) can only be backtested over
   a shallow recent window** (~38 sessions @15m). For longer history we
   approximate the BB-bounce entry on **daily** bars and label it clearly as a
   coarse proxy. Daily-close entry keepers (`v2_14dte_atm`, `v2_28dte_atm`, …)
   backtest cleanly over years.

**Net fidelity grade:** underlying path = HIGH; option premium path =
LOW→MEDIUM (modeled); fills/slippage = MEDIUM (reuse `paper_economics`); UW
alpha overlays (flow/gex/iv) = NOT backtestable historically. ⇒ This tool is a
**relative ranker**, not an absolute-P&L oracle.

---

## Architecture

New package `xsp_killer/backtest/` + one CLI. Reuse existing pure functions;
invent nothing that already exists.

```
xsp_killer/backtest/
  __init__.py
  bars.py         # data source: fixture | uw. Caches under .local/uw_cache/
  option_model.py # synth call premium path from underlying (BS-lite + fallback)
  engine.py       # replay loop; reuses evaluate_exit_alerts + lane_a_ta + paper_economics
  variants.py     # resolve config/lane_a_variants.yaml overrides -> params (reuse existing resolver)
  sweep.py        # small bounded grid over param axes
  report.py       # ranking table (md/json) + optional MCPT-lite
scripts/
  backtest_lane_a.py   # CLI entry point
tests/
  test_backtest_engine.py
  fixtures/backtest/    # tiny committed synthetic OHLC so offline tests pass
```

**Cache dir:** `.local/uw_cache/` — already gitignored via `.local/` in
`.gitignore` (confirmed line 7). Cache key mirrors TipDrop's
`uw:hist:{ticker}:{period}:{interval}`; store as parquet/CSV keyed by that. UW
provider *also* caches internally, so we cache the DataFrame locally to survive
process restarts and to run offline once warmed.

**Reused building blocks (do not reimplement):**
- Exit engine: `xsp_killer.lane_a_monitor.evaluate_exit_alerts(pos, rules, now_et=, ta_signal=)`
  — pure given a position object exposing `mark_price`, return-pct, `dte`,
  `mark_quote_stale`. The engine feeds it synthesized marks per bar.
- TA: `xsp_killer.lane_a_ta.enrich_bars`, `detect_bb_bounce_entry`,
  `detect_upper_bb_touch`, `detect_upper_bb_exit`, `_bar_snapshot`,
  `evaluate_ta_signals` — all operate on DataFrames/snapshots, so historical
  bars feed straight in.
- Economics: `xsp_killer.paper_economics.entry_fill_premium`,
  `exit_fill_premium`, `pnl_from_entry_fill`, `pnl_pct`, `scale_spy_premium`,
  `load_premium_scale`.
- Entry selection: `xsp_killer.lane_a_entry.round_xsp_strike`, `pick_strike`
  (mode dispatch), `estimate_fallback_premium`; DTE via `dte_target`/`dte_pick`
  (compute expiry = entry_date + target calendar days for backtest, since we
  have no historical expiry calendar).
- Regime gate: `xsp_killer.macro_regime` EMA/SMA helpers on daily closes to
  reproduce GREEN / YELLOW; DIP_BOUNCE reproduced from BB-bounce on the bar path.
- Variant resolve: the override-merge logic already in
  `xsp_killer/lane_a_variants.py` (loads `config/lane_a_variants.yaml`,
  deep-merges `overrides` onto `lane_a_rules.yaml`). Wrap it, don't fork it.

**Position shim.** The engine builds a lightweight object (or reuses
`LaneAPosition` if constructable offline) carrying `entry_ts`, `dte`,
`entry_mid_premium`, `mark_price`, `average_price`, `pnl_usd`,
`pnl_per_contract`, `mark_quote_stale=False`. `evaluate_exit_alerts` only reads
these; we set `mark_price` from `option_model` each step.

---

## MVP phases for TODAY

### Phase A — fixture replay + variant sweep (offline, ships FIRST, no key)
- `bars.py` fixture loader reads committed `tests/fixtures/backtest/spy_daily.csv`
  (and a short intraday CSV). Deterministic, no network.
- `option_model.py` BS-lite (or `estimate_fallback_premium` fallback) turns the
  underlying path into a call-premium path per (strike, entry_dte, iv_seed).
- `engine.py` runs one variant end-to-end: pick expiry+strike at the entry bar,
  step bars, call `evaluate_exit_alerts` (+ TA) until exit/`max_hold_dte`,
  record a trade row (`entry_ts, exit_ts, dte, strike, exit_reason,
  net_pnl_pct, pnl_usd`).
- `sweep.py` runs the **active keeper variants** (`active: true` in
  `lane_a_variants.yaml`) via the resolver.
- CLI prints ranked table; writes `reports/backtest/lane_a_bt_<ts>.json`.
- **Gate: `pytest tests/test_backtest_engine.py` green offline.**

### Phase B — UW OHLC fetch + cache, same engine (when key present)
- `bars.py` uw loader: import TipDrop provider exactly like `uw_shadow._get_provider()`
  (`XSP_UW_TIPDROP_ROOT` on `sys.path`, `data.fetcher.get_provider`), call
  `get_history("SPY", period, "1d")` and `get_intraday("SPY", "15m", period)`.
  **Fail-open:** if no key / import fails / empty frame ⇒ fall back to fixture
  mode with a loud log line (mirrors `uw_shadow` fail-open contract).
- Cache each frame to `.local/uw_cache/`. Budget note: this is a *handful* of
  calls total (SPY only, cached), trivially inside the ~120/min ~100k/day shared
  budget — the real constraint is dev time, not API.
- Engine byte-identical to Phase A; only the data source swaps.

### Phase C — report ranking + optional MCPT-lite
- `report.py`: markdown + JSON with per-variant rows: `n_trades, win%,
  mean_net_pnl_pct, median, total_pnl (scaled + ~1ct), exit-reason histogram,
  max_hold hits`. Sort by mean net %.
- **Healthy window** recommendation: for each swept axis, flag the value(s)
  whose bucket has positive mean net % **and** MCPT `pass_5pct`. Everything else
  = "noise / needs soak."
- MCPT-lite: port `mcpt(pnl_pct, n_perm)` from
  `/tmp/llm-wiki-by-cemini/scripts/backtest_common/mcpt_gate.py` into
  `xsp_killer/backtest/report.py` (self-contained, numpy-only; sign-flip
  permutation, H0: mean=0, `pass_5pct = p<0.05 and mean>0`). Guarded by
  `--mcpt`; skipped gracefully if `numpy` missing.
- Optional: emit an HTML sweep report via the wiki's
  `scripts/cemini_backtest_report/` kit only if time remains — JSON+md is the
  MVP.

---

## Parameter axes to sweep (map to existing variant knobs — keep grid SMALL)

Do **not** run a full factorial. Run: (1) all active keeper variants as-is, then
(2) **one axis micro-sweep at a time** around the current dip-swing base. Axes,
mapped to real knobs in `config/lane_a_variants.yaml` / `lane_a_rules.yaml`:

| Axis | Knob(s) | Small grid |
|---|---|---|
| Runway / DTE | `entry.dte_pick` + `entry.dte_target` | `min(~14)`, `21`, `28` |
| Strike | `entry.strike_pick` | `atm_only`, `cheapest_near_atm`, `otm_one` |
| Take-profit | `exit.take_profit_pct` | `0.20`, `0.25`, `0.40`, `0.60` |
| Stop-loss | `exit.stop_loss_pct` | `0.20`, `0.50` |
| Regime gate | `entry.regime_gate` | `GREEN`, `DIP_BOUNCE` |
| Swing hold | `exit.swing_hold` + `exit.max_hold_dte` | off, on(`max_hold_dte=2`) |

Budget ceiling for today: **≤ ~40 total runs** (≈12 keepers + one 4–6 point
sweep on each of 2–3 axes). Each run is in-memory over cached bars ⇒ seconds.

---

## Success criteria / how the operator runs it after key paste

1. Operator installs key per `/opt/tipdrop-scanner/INSTALL-UW-KEY-HETZNER.md`
   (`UNUSUAL_WHALES_API_KEY`), and sets `XSP_UW_TIPDROP_ROOT=/opt/tipdrop-scanner`.
2. Warm + rank:
   ```bash
   cd /opt/xsp-killer
   python3 scripts/backtest_lane_a.py --mode uw --start 2024-01-01 \
       --variants active --sweep tp,dte --mcpt --out reports/backtest/
   ```
3. Read `reports/backtest/lane_a_bt_<ts>.md`: ranked variants + "healthy
   window" section. Feed winners into the soak scoreboard, deprioritize losers.

**Success =** ranked table produced from real UW SPY history, MCPT column
present, recommendations reproducible, zero `LIVE_*` touched, runs offline in
fixture mode for CI.

---

## Test plan

- `tests/test_backtest_engine.py` (offline, fixture-only):
  - A synthetic up-drift path yields a `take_profit` exit; a crash path yields
    `stop_loss`; a flat path near expiry yields `max_hold`/`time_stop`.
  - Determinism: same seed/fixture ⇒ identical trade rows.
  - Fail-open: `--mode uw` with no key falls back to fixture + logs, exit 0.
  - MCPT: `n_trades<5` ⇒ `pass_5pct=False`, no crash.
- Reuse-contract test: engine calls the **real** `evaluate_exit_alerts` /
  `paper_economics` (no monkeypatched fakes) so drift in prod rules is caught.
- `ruff check xsp_killer/backtest scripts/backtest_lane_a.py` clean.
- No network in the test suite (fixtures committed under `tests/fixtures/backtest/`).

---

## Explicit disclaimer — does NOT replace the paper soak

This backtest ranks variants on a **modeled** option-premium path derived from
SPY underlying OHLC. It has **no historical option fills, no historical IV
surface, and no UW flow/gex history** — those overlays are forward-only. Premium
synthesis is a proxy; absolute P&L is indicative, not real. Rankings are for
**prioritization only**: they tell us which variants deserve soak attention and
which parameter windows to stop wasting soak slots on. **LIVE promotion still
requires the live paper soak** (real RH marks, real session microstructure,
real fills). No `LIVE_ENTRIES` / `LIVE_EXITS` / `LIVE_*` is enabled by this
work, and this tool must never be cited as soak substitute for go/no-go.
