# Nagus backtest sensor

Lane A backtest ranker → Nagus ops control plane (brain + filesystem queue + staging packets).

## Concept

This package is the **backtest-sensor analog** of the OSINT `scripts/xsp_ops/` MVP: same brain / queue / packet shapes, self-contained under `/opt/xsp-killer` (no `intel.core`, no Notion/Linear).

Canonical concept: `@concepts/nagus-ops-control-plane.md`  
(laptop OSINT wiki: `/tmp/llm-wiki-by-cemini/wiki/concepts/nagus-ops-control-plane.md`)

## What it does

After `scripts/backtest_lane_a.py` writes `reports/backtest/lane_a_bt_*.json`:

1. **Brain audit** — append one `pull_log` entry (`state/brain.json`)
2. **Post records** — one JSON per candidate under `state/posts/`
3. **Queue jobs** — pending review jobs under `queue/pending/`
4. **Packets** — staging markdown under `packets/` when action is `packet`
5. **Scale event** — optional `events/escalate_*.json` when pending ≥ threshold

Humans still promote packets → `briefs/`. This loop only *stages*.

## Ops root

| Source | Path |
|--------|------|
| Env | `$XSP_OPS_ROOT` |
| Default | `.local/ops/xsp/` (gitignored) |

## CLI

```bash
# Primary: emit after a backtest run
python3 scripts/backtest_lane_a.py --mode fixture --mcpt --nagus
python3 scripts/backtest_lane_a.py --mode fixture --nagus-dry-run

# Re-emit from newest report (no engine re-run)
python3 scripts/nagus_backtest_sensor.py --from-latest
python3 scripts/nagus_backtest_sensor.py --report reports/backtest/lane_a_bt_....json
python3 scripts/nagus_backtest_sensor.py --from-latest --dry-run
XSP_OPS_ROOT=/tmp/soak python3 scripts/nagus_backtest_sensor.py --from-latest
```

## Hard stops

- No `LIVE_ENTRIES` / `LIVE_EXITS` flips
- No auto-write to `briefs/` or `wiki/`
- Emit is fail-open: ops errors never fail the backtest CLI
- No Notion / Linear / Discord / Robinhood clients

## Package

```
xsp_killer/ops/
  state.py          # atomic JSON + utc_now_iso
  paths.py          # XSP_OPS_ROOT layout
  brain.py          # pull_log + bt_* keys
  queue.py          # find_job / write_pending
  rules.py          # classify_variant (MCPT / top-K / watch)
  packet_render.py  # staging markdown
  emit.py           # emit_from_report
```

See `briefs/2026-07-16_nagus-backtest-sensor-plan.md` for the full data contract and rules table.
