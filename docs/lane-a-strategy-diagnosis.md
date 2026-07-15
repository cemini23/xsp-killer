# Lane A strategy diagnosis (refreshed 2026-07-15)

## Current posture

| Mode | Status |
|------|--------|
| Paper soak (VPS) | **GO** — primary measurement path |
| Live RH entries/exits | **NO-GO** — keep `LIVE_ENTRIES=false` / `LIVE_EXITS=false` |
| Strategy pivot | **Dip-swing** cluster + session-open exits (not clock-gated morning cut) |

## Pivot: dip-swing + session-open exits

### Entry thesis
- **Dip-bounce** (`regime_gate: DIP_BOUNCE`): BB bounce + VWAP reclaim; not GREEN-only close-window only.
- Active keepers include `v2_dip_swing_14dte*`, `v2_dip_swing_21dte*`, plus legacy DTE/ATM/yellow-bounce shadows.
- **Far-DTE OTM operator thesis:** one re-enabled shadow `v2_dip_swing_55dte_otm` (v9 P2 #15) with variant-only **`dte_max: 65`** (fixes 55/60 Friday collision under baseline 60). 45/50/60 DTE OTM remain **inactive** to avoid confounded multi-bucket load.
- **Lane A⅔ mid-tenor:** active shadow `v2_mid_tenor_80dte_atm` (~80 DTE ATM, `dte_max: 90` override only) shadows mentor monthly–quarterly XSP (e.g. 9/30). Capacity: `v2_28dte_green_day` deactivated. **Not** merged into overnight `lane_a_rules.yaml` `dte_max: 60`.

### Exit thesis (session-open)
- Exit whenever Cboe XSP is tradeable (**GTH / RTH / curb**), when TP / SL / BB conditions hit.
- **No** clock sell / no-sell window; daily morning `time_stop` removed.
- Swing-hold near-expiry cut via `max_hold_dte` only.
- **GTH liquidity (v9 P1 #13):** limit price off **bid** outside RTH; wide spread `(ask-bid)/ask > 0.25` **vetoes take-profit** (stop-loss may still fire, priced at bid).

### Conductor shadow vs DIP_BOUNCE
- `conductor_shadow` blocks day-after SPY &lt; −1.5% (and RED regime) — can **starve** dip-bounce entries.
- Telemetry exposes `conductor_shadow_skip_count` vs `dip_bounce_sessions` (v9 P1 #14).

## Prune state (2026-07-13 focus prune + v9 follow-up)

Pruned as **identical-book clones** or starved far-DTE (see `config/lane_a_variants.yaml` comments):

| Variant | Why inactive |
|---------|----------------|
| `v2_28dte_cheapest` | Clone of `v2_28dte_atm` |
| `v2_28dte_wide_sl` | Clone of `v2_28dte_easy_tp` |
| `v2_yellow_top_quartile_bounce` | Clone of `v2_yellow_mid_bounce` |
| `v2_dip_swing_14dte_loose` / `30dte` | Identical / capacity prune |
| `v2_dip_swing_{45,50,60}dte_otm` | Far-DTE OTM; **55 only** re-enabled for single-bucket shadow |
| `v2_28dte_green_day` | Capacity 2026-07-15 → freed for `v2_mid_tenor_80dte_atm` (Lane A⅔) |
| Older ATM 35/45/60 nets | Prior soak negatives under **old** exit regime |

Promotion reporting **collapses confounded clone families** so eligible-review lists do not triple-count one book (`promotion_summary.clone_families`).

## Historical bugs (still relevant context)

| Issue | Fix | Location |
|-------|-----|----------|
| same-day `time_stop` | Removed clock forced cut; session-open only | `evaluate_exit_alerts` |
| half-step OTM | `otm_one` → ATM + 5.0 XSP | `lane_a_entry.pick_strike` |
| fallback premium | OTM scale by steps from ATM | `estimate_fallback_premium` |
| prior-day SPY | Optional filter; dip-swing often `false` | entry rules |
| zero-mark / stale TP | SL fires on stale; TP suppressed | `mark_quote_stale` |

## Variant soak ops

```bash
python3 scripts/lane_a_variants.py entry
python3 scripts/lane_a_variants.py monitor
python3 scripts/lane_a_variants.py scoreboard
```

Scoreboard: `briefs/xsp-lane-a-variants-scoreboard.json`

### Regime gate experiment (still tracked)

| Variant | Regime gate | Track family |
|---------|-------------|--------------|
| `v2_baseline_prod` | `GREEN` | `baseline_green` |
| `v2_yellow_mid_bounce` | `GREEN_OR_YELLOW_BOUNCE` | `yellow_bounce_frac_axis` |
| dip-swing keepers | `DIP_BOUNCE` | (dip-swing cluster) |

**Promotion:** WAIT until ≥20 post-epoch sessions **and** ≥20 closed trades; Wilson LB vs breakeven; no confounded clone double-count.

## Stale / GTH paper marks

- Paper marks use SPY chain proxy (`spy_quote`); prefer **bid** on wide spreads.
- Overnight GTH paper fills can be optimistic vs live XSP liquidity — treat GTH paper exits as upper bound until live bid/ask soak.
- Outside hours / empty chain → `mark_quote_stale`; TP vetoed; SL may still fire on clamped mark.

## Tooling watch (K168) — no order-path deps

**Bonsai** (local low-bit LLM) and **Undici** (Node HTTP pooling) are eval / future REST hedges only. **Never** put them on the Robinhood place path. No runtime dependency; keep `LIVE_ENTRIES` / `LIVE_EXITS` false. See `docs/rh_mcp_claudio.md`.
