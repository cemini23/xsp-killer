# Nagus backtest sensor — implementation plan (Lane A ranker → ops control plane)

- **Status:** DONE (2026-07-16)
- **Date:** 2026-07-16
- **Repo:** `/opt/xsp-killer` @ `074d022`
- **Scope:** ~1–2h Grok pass. Wire the existing Lane A UW/fixture backtest ranker into the Nagus ops control-plane pattern.
- **Concept:** `@concepts/nagus-ops-control-plane.md` (laptop OSINT wiki: `/tmp/llm-wiki-by-cemini/wiki/concepts/nagus-ops-control-plane.md`)
- **Reference MVP (do NOT copy wholesale):** `/tmp/llm-wiki-by-cemini/scripts/xsp_ops/` (README + `paths.py`, `brain.py`, `queue.py`, `enqueue.py`, `triage_rules.py`, `packet_render.py`, `scale.py`, `cli.py`)

---

## Goal

After `scripts/backtest_lane_a.py` produces a ranked report (`reports/backtest/lane_a_bt_*.json`), emit **Nagus-compatible ops state** so the ops loop can treat the backtest as just another **sensor**:

1. **Brain audit** — append one `pull_log` entry per backtest run (mode/source, counts, top variant).
2. **Post records** — one structured record per *candidate* variant window under `state/posts/`.
3. **Optional queue job** — enqueue candidate variants for human review (`queue/pending/`).
4. **Packet** — emit a staging markdown packet when a healthy window / MCPT-pass variant appears.
5. **Optional scale event** — escalate when the candidate backlog crosses a threshold.

The human still promotes packets → `briefs/`. This loop only *stages*.

## Done (acceptance)

- `python3 scripts/backtest_lane_a.py --mode fixture --sweep dte --mcpt --nagus` writes the normal report **and** populates `$XSP_OPS_ROOT` (or `.local/ops/xsp/`) with `state/brain.json`, `state/posts/*.json`, `queue/pending/*.json`, and `packets/*.md` for qualifying variants.
- `python3 scripts/nagus_backtest_sensor.py --from-latest` re-emits from the newest report JSON without re-running the engine.
- Emit is **fail-open**: any ops error is logged and swallowed; the backtest CLI still returns `0` and still writes the report.
- New helper package `xsp_killer/ops/` is **self-contained** — no `intel.core`, no `xsp_ops` import, no Notion/Linear/Discord clients required.
- Tests pass offline with a tmp ops root via `XSP_OPS_ROOT`; `ruff check .` clean.

## Non-goals / hard stops

- No `LIVE_*` flags touched (`LIVE_ENTRIES` / `LIVE_EXITS` stay as-is). Backtest stays read-only.
- **No auto-write to `briefs/`** or `wiki/`. Packets land only under the ops root.
- No Notion / Linear / Discord / Robinhood clients. (macOS `osascript` notify is optional and off by default on a Linux Hetzner box.)
- No dependency on the OSINT `intel.core` module or the full `scripts/xsp_ops/` package. The OSINT package is a **mirror reference only**.
- No secrets, no network beyond what the existing `--mode uw` path already does.
- Backtest engine (`xsp_killer/backtest/*`) is **not** modified except a thin, optional post-write hook.

---

## Data contract

All timestamps are UTC ISO-8601 (`utc_now_iso()` → `2026-07-16T12:00:00+00:00`). Slugs are filesystem-safe: `bt_<reportStem>_<variant_id>` sanitized to `[\w\-]`.

### 1. Brain `pull_log` entry (`state/brain.json` → `pull_log[]`)

One appended per backtest run (capped to last 20, matching the MVP `PULL_LOG_MAX`).

```json
{
  "at": "2026-07-16T12:00:00+00:00",
  "sensor": "backtest_lane_a",
  "mode": "uw",
  "source": "unusual_whales",
  "report_json": "reports/backtest/lane_a_bt_20260716T120000Z.json",
  "report_md": "reports/backtest/lane_a_bt_20260716T120000Z.md",
  "n_variants": 12,
  "n_candidates": 4,
  "n_mcpt_pass": 2,
  "top_variant": "sweep_dte_1",
  "top_mean_net_pct": 0.0123,
  "dry_run": false
}
```

Brain top-level shape (extends the MVP `DEFAULT_BRAIN`; backtest-specific keys additive so a shared root stays compatible with the OSINT sensor):

```json
{
  "last_pull_at": "2026-07-16T12:00:00+00:00",
  "items_seen": 12,
  "pull_log": [ /* entries above, last 20 */ ],
  "bt_post_ids": ["bt_20260716T120000Z_sweep_dte_1"],
  "bt_known_reports": ["reports/backtest/lane_a_bt_20260716T120000Z.json"]
}
```

> Use additive keys (`bt_*`) instead of reusing the OSINT `post_ids` / `known_paths`, so a single shared `.local/ops/xsp/` root can host both the Macro-Charts sensor and the backtest sensor without collisions.

### 2. Post record (`state/posts/<slug>.json`)

One per **candidate** variant (see Rules). Derived straight from a `ranking[]` row in the report payload plus classification.

```json
{
  "slug": "bt_20260716T120000Z_sweep_dte_1",
  "kind": "backtest_variant",
  "sensor": "backtest_lane_a",
  "variant_id": "sweep_dte_1",
  "report_json": "reports/backtest/lane_a_bt_20260716T120000Z.json",
  "report_md": "reports/backtest/lane_a_bt_20260716T120000Z.md",
  "generated_at": "2026-07-16T12:00:00+00:00",
  "mode": "uw",
  "source": "unusual_whales",
  "n_trades": 42,
  "win_pct": 57.14,
  "mean_net_pnl_pct": 0.0123,
  "median_net_pnl_pct": 0.008,
  "total_pnl_usd": 512.34,
  "mcpt_p": 0.032,
  "mcpt_pass_5pct": true,
  "status": "healthy",
  "priority": "high",
  "action": "packet",
  "reason": "mcpt pass_5pct (p=0.032); mean_net%>0",
  "landed_at": "2026-07-16T12:00:01+00:00",
  "packet_path": null
}
```

`status` ∈ `healthy | candidate | watch | noise`. `action` ∈ `packet | watch | skip`. `priority` ∈ `high | med | low`. Field names mirror the report's `ranking[]` row (`variant_id`, `n_trades`, `win_pct`, `mean_net_pnl_pct`, `median_net_pnl_pct`, `total_pnl_usd`, `mcpt_p`, `mcpt_pass_5pct`) so mapping is a copy, not a transform.

### 3. Queue job (`queue/pending/<slug>.json`)

```json
{
  "slug": "bt_20260716T120000Z_sweep_dte_1",
  "created_at": "2026-07-16T12:00:01+00:00",
  "status": "pending",
  "kind": "backtest_variant",
  "sensor": "backtest_lane_a",
  "variant_id": "sweep_dte_1",
  "priority": "high",
  "action": "packet",
  "report_json": "reports/backtest/lane_a_bt_20260716T120000Z.json"
}
```

Idempotent: if a job for `slug` already exists in any bucket (`pending|running|done|failed`), skip (re-uses MVP `find_job` semantics). Human/triage moves `pending → done|failed` later; this sensor never advances jobs itself.

### 4. Packet markdown skeleton (`packets/YYYY-MM-DD_<slug>.md`)

Only for `action == "packet"` without an existing packet file. Never under `briefs/`.

```markdown
# XSP backtest packet: sweep_dte_1

## Target

CeminiSuite / xsp-killer — Lane A variant review

## Summary

Lane A backtest flagged `sweep_dte_1` as a **healthy window** (MCPT pass_5pct, p=0.032).
Modeled premiums only — relative ranker, NOT a LIVE promotion.

| Field | Value |
|-------|-------|
| variant_id | `sweep_dte_1` |
| status / priority | healthy / high |
| mode / source | uw / unusual_whales |
| n_trades | 42 |
| win% | 57.14 |
| mean net% | 1.23 |
| median net% | 0.80 |
| total $ | 512.34 |
| MCPT p / pass@5% | 0.032 / True |
| report | `reports/backtest/lane_a_bt_20260716T120000Z.json` |

## Body

### Why flagged

mcpt pass_5pct (p=0.032); mean_net%>0; n_trades≥20.

### Disclaimer

Modeled option premiums from SPY OHLC (BS-lite). Not historical fills.
Relative ranker only — does NOT replace paper soak for LIVE promotion.
`LIVE_ENTRIES`/`LIVE_EXITS` untouched.

### Operator notes

- Packet is **staging only** under `.local/ops/xsp/packets/`.
- Human promote ritual: copy to `briefs/xsp-YYYY-MM-DD_<slug>.md` after review.
- Do NOT auto-ship to prod, wiki, or `briefs/`.

### Next steps

1. Confirm the window holds on a longer UW period / different seed.
2. If keep: promote to `briefs/` and run a paper soak before any LIVE change.
3. If noise: leave packet in place; no `briefs/` write.
```

### 5. Optional scale event (`events/escalate_<ts>.json`)

```json
{
  "type": "escalate",
  "at": "2026-07-16T12:00:02+00:00",
  "sensor": "backtest_lane_a",
  "pending": 6,
  "threshold": 5,
  "reasons": ["pending_ge_threshold"],
  "message": "XSP backtest ops escalate: pending=6 candidates awaiting review"
}
```

Threshold via `XSP_OPS_SCALE_PENDING` (default 5), mirroring the MVP. On Linux (Hetzner) notification is a **no-op by default** — write the event JSON only; do not shell out to `osascript`. (Discord is out of scope.)

---

## File layout under `/opt/xsp-killer`

New self-contained package + thin CLI. Nothing imports `intel.core` or `xsp_ops`.

```
xsp_killer/ops/
  __init__.py
  state.py          # atomic read_json / write_json / utc_now_iso (stdlib only)
  paths.py          # OPS_ROOT (env XSP_OPS_ROOT else .local/ops/xsp), ensure_layout, path helpers
  brain.py          # load_brain / save_brain / append_pull_log (bt_* additive keys)
  queue.py          # find_job / write_pending (idempotent; no auto-advance)
  rules.py          # classify_variant(row, cfg) -> {status, priority, action, reason}
  packet_render.py  # render_packet_markdown(post) + write_packet + existing_packet_for_slug
  emit.py           # emit_from_report(payload, *, root, dry_run) -> summary dict (fail-open)

scripts/
  nagus_backtest_sensor.py   # thin CLI: --from-latest | --report PATH | --dry-run

scripts/backtest_lane_a.py   # add --nagus flag -> calls ops.emit.emit_from_report(payload)

tests/
  test_nagus_backtest_sensor.py

briefs/
  2026-07-16_nagus-backtest-sensor-plan.md   # this file

docs/ (optional, 1 short page)
  nagus-backtest-sensor.md   # operator pointer + link to @concepts/nagus-ops-control-plane.md
```

### `state.py` (the only "port" from OSINT)

Re-implement the two functions the OSINT package pulls from `intel.core.state`, stdlib only:

```python
def read_json(path: Path, default): ...        # return default on missing/corrupt
def write_json(path: Path, data) -> None: ...   # mkdir parents; atomic write via tmp + os.replace
def utc_now_iso() -> str: ...                    # datetime.now(timezone.utc), microsecond=0
```

Atomic write (tmp file in same dir + `os.replace`) matters because the shared root may be read by a concurrent OSINT loop.

### `paths.py`

Mirror the MVP but rooted at the xsp-killer repo:

```python
_OVERRIDE = os.environ.get("XSP_OPS_ROOT")
OPS_ROOT = Path(_OVERRIDE) if _OVERRIDE else (REPO_ROOT / ".local" / "ops" / "xsp")
```

`ensure_layout()` creates `state/posts`, `queue/{pending,running,done,failed}`, `packets`, `events`. All path helpers take an optional `root` arg so tests pass a tmp dir directly (don't rely solely on env in-process).

---

## CLI UX

Two entry points; both call the same `emit.emit_from_report`.

### A. `--nagus` flag on the backtest CLI (primary path)

Add to `scripts/backtest_lane_a.py` `_build_parser()`:

```
--nagus            Emit Nagus ops state (brain/posts/queue/packets) after writing the report
--nagus-dry-run    Compute + print the emit plan without durable ops writes
```

Wire after `write_report(...)`, fail-open:

```python
json_path, md_path = write_report(payload, out_dir)
print_ranking_table(payload)
if args.nagus or args.nagus_dry_run:
    try:
        from xsp_killer.ops.emit import emit_from_report
        summary = emit_from_report(
            payload,
            report_json=json_path,
            report_md=md_path,
            dry_run=args.nagus_dry_run,
        )
        print(f"[nagus] {summary}")
    except Exception as exc:  # fail-open: report already written
        logger.warning("nagus emit failed (non-fatal): %s", exc)
```

### B. `scripts/nagus_backtest_sensor.py` (re-emit / cron role)

Thin role — does **not** run the engine. Reads an existing report JSON and emits.

```bash
# Re-emit from newest reports/backtest/lane_a_bt_*.json
python3 scripts/nagus_backtest_sensor.py --from-latest

# Emit from a specific report
python3 scripts/nagus_backtest_sensor.py --report reports/backtest/lane_a_bt_20260716T120000Z.json

# Plan only, no writes
python3 scripts/nagus_backtest_sensor.py --from-latest --dry-run

# Override ops root (matches env; useful for tests / alt soak dirs)
XSP_OPS_ROOT=/tmp/soak python3 scripts/nagus_backtest_sensor.py --from-latest
```

Args: `--report PATH` | `--from-latest` (glob newest `lane_a_bt_*.json` under `reports/backtest/` or `--out-dir`), `--out-dir`, `--dry-run`, `--ops-root`. Exit `0` on success, `0` on fail-open with a warning (never blocks the pipeline); `2` only on bad args (e.g. no report found with `--report`).

---

## Rules — when to enqueue / when to packet

Rules live in `rules.py`, pure functions over a `ranking[]` row, config via constants + env overrides. No LLM calls (mirrors `triage_rules.py` discipline).

Config (defaults; env-overridable):

| Knob | Env | Default | Meaning |
|------|-----|---------|---------|
| `MIN_TRADES` | `XSP_BT_MIN_TRADES` | `20` | Minimum `n_trades` for a variant to be trustworthy |
| `MIN_MEAN_PCT` | `XSP_BT_MIN_MEAN_PCT` | `0.002` | Min `mean_net_pnl_pct` (0.2%) for a top-K candidate |
| `TOP_K` | `XSP_BT_TOP_K` | `3` | Rank cutoff for the top-K mean-net% path |

`classify_variant(row, rank)` decision (evaluate top → bottom, first match wins):

1. **`mcpt_pass_5pct is True`** → `status=healthy`, `action=packet`, `priority=high`, reason `"mcpt pass_5pct (p=…)"`.
2. **`mcpt_pass_5pct is False`** → `status=noise`, `action=skip`, `priority=low`, reason `"mcpt fail; needs soak"`. (Explicit MCPT failure vetoes even a good mean.)
3. **MCPT not run (`mcpt_pass_5pct is None`)** and `rank ≤ TOP_K` and `mean_net_pnl_pct ≥ MIN_MEAN_PCT` and `n_trades ≥ MIN_TRADES` → `status=candidate`, `action=packet`, `priority=med`, reason `"top-K mean net% (rank=…, n≥…)"`.
4. **`mean_net_pnl_pct > 0`** and `n_trades ≥ MIN_TRADES` → `status=watch`, `action=watch`, `priority=low`, reason `"positive but not top-K / no MCPT"`.
5. **Else** → `status=noise`, `action=skip`.

Emit behavior per action:

- `action == "packet"` → write post record + enqueue pending job + write packet markdown.
- `action == "watch"` → write post record + enqueue pending job (no packet). (Keeps it visible for human triage without a full packet.)
- `action == "skip"` → **not** landed, **not** enqueued (avoids flooding state with noise).

> Rationale: rule 1 is the concept's "MCPT-pass variant"; rule 3 is the "healthy window / top-K mean net% with n_trades≥N" path when MCPT wasn't run. `healthy_windows()` already exists in `report.py` but only covers `sweep_*` ids — `rules.py` generalizes to any variant and is the single source of truth for the sensor.

`n_candidates` in the pull_log = count of rows with `action in {packet, watch}`. `n_mcpt_pass` = count of `mcpt_pass_5pct is True`.

---

## Test plan

New file `tests/test_nagus_backtest_sensor.py`. Fully offline; set a tmp ops root via `XSP_OPS_ROOT` (monkeypatch env) **and** pass `root=tmp_path/"ops"` explicitly to be robust to in-process env caching.

Fixtures: build a small synthetic `payload` dict inline (2–3 `ranking` rows) rather than running the engine — fast + deterministic. Cover:

1. **`test_emit_creates_layout`** — `emit_from_report` on a payload creates `state/brain.json`, `queue/pending/`, `packets/` under the tmp root.
2. **`test_mcpt_pass_emits_packet`** — a row with `mcpt_pass_5pct=True` → post record `action=packet`, one `queue/pending/*.json`, one `packets/*.md` containing the variant id.
3. **`test_mcpt_fail_skipped`** — `mcpt_pass_5pct=False` → no post record, no queue job, no packet.
4. **`test_topk_mean_candidate`** — MCPT `None`, rank 1, `mean_net_pnl_pct≥MIN_MEAN_PCT`, `n_trades≥MIN_TRADES` → `action=packet` (candidate/med).
5. **`test_low_trades_watch_or_skip`** — positive mean but `n_trades < MIN_TRADES` → not `packet` (watch or skip; no packet file).
6. **`test_idempotent_reemit`** — emitting the same payload twice does not duplicate queue jobs or packets (uses `find_job` + `existing_packet_for_slug`).
7. **`test_pull_log_appended_and_capped`** — brain `pull_log` gets one entry per emit; length capped at 20.
8. **`test_dry_run_no_writes`** — `dry_run=True` writes nothing durable but returns a non-empty summary.
9. **`test_fail_open_in_cli`** — monkeypatch `emit_from_report` to raise; assert `scripts/backtest_lane_a.py --mode fixture --nagus` still exits `0` and still wrote the report. (Or unit-test the try/except wrapper.)
10. **`test_from_latest_picks_newest`** — write two report JSONs with different stems into a tmp out-dir; `--from-latest` selects the newest.
11. **`test_no_briefs_write`** — assert nothing is created under `briefs/` or `wiki/` during any emit (guard against regressions).

Run:

```bash
cd /opt/xsp-killer
XSP_OPS_ROOT=$(mktemp -d) python3 -m pytest tests/test_nagus_backtest_sensor.py -q
ruff check .
```

---

## Operator runbook (after David's UW key lands on Hetzner)

Pre-req: `.local/` is already gitignored; the ops root defaults to `.local/ops/xsp/`. No `briefs/` writes happen automatically.

1. **Sanity (fixture, no key):**
   ```bash
   python3 scripts/backtest_lane_a.py --mode fixture --sweep dte --mcpt --nagus
   ls .local/ops/xsp/{state,queue/pending,packets}
   ```
2. **Real run with UW key** (uses existing `--mode uw` path; fails open to fixtures if key/provider missing):
   ```bash
   python3 scripts/backtest_lane_a.py --mode uw --period 2y --sweep dte,tp,sl --mcpt --mcpt-perm 2000 --nagus
   ```
3. **Review the brain + candidates:**
   ```bash
   cat .local/ops/xsp/state/brain.json | python3 -m json.tool | sed -n '1,40p'
   ls .local/ops/xsp/queue/pending/
   ls .local/ops/xsp/packets/
   ```
4. **Promote (human-only):** open a packet in `.local/ops/xsp/packets/`, confirm the window holds, then **manually** copy to `briefs/xsp-YYYY-MM-DD_<slug>.md`. Never `scp` a packet straight to prod; run a paper soak before any LIVE change.
5. **Re-emit without recompute** (e.g. after tuning rules/env): `python3 scripts/nagus_backtest_sensor.py --from-latest`.
6. **Optional hourly cron/systemd** (Cursor wires later, not in this pass): run `scripts/nagus_backtest_sensor.py --from-latest` after the scheduled backtest. Escalation events land in `.local/ops/xsp/events/`; check with `ls .local/ops/xsp/events/`.

**Hard stops on Hetzner:** no `LIVE_*` flips; no auto-`briefs/`; no Notion/Linear/Discord; `.local/` stays untracked.

---

## Mirror-docs note (optional, if time)

Add a one-line cross-link in `docs/nagus-backtest-sensor.md` (or the xsp-killer README) pointing at `@concepts/nagus-ops-control-plane.md` and stating this package is the **backtest-sensor analog** of the OSINT `scripts/xsp_ops/` MVP — same brain/queue/packet shapes, self-contained (no `intel.core`), no Macro-Charts sensor.

## Explicit concept link

This plan implements the "treat a producer as a **sensor** feeding a `.local` brain + filesystem queue + staging packets, human-promote to briefs" pattern from `@concepts/nagus-ops-control-plane.md`.
