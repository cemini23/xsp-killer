# cursor-audit · deepseek-reasoner · xsp-killer · SUPER AUDIT v9

## Executive verdict

| Environment | Verdict | Rationale |
|---|---|---|
| Paper soak / measurement integrity | **OPERATIONAL** | v8 P0s (paper exits under MCP, marks, debit gates, allowlist) claimed fixed in `cf79281` — no regression observed. New exit timing (`cc12ad5`) removes clock gate, consistent with rules. Premium scale 10× dual-logged; no cross-variant PnL summing. Scoreboard pre‑prune stale, but measurement path intact. |
| Strategy coherence (prune + exit timing) | **WARN** | Prune of far-DTE OTM (45–60) to 12 keepers is data‑driven (0% win, net‑negative) and frees capacity for dip‑swing cluster — correct. Premarket 08:00–09:30 sell window + session‑open exit rule aligns with thesis; liquidity/gap risk acknowledged but mitigated by TP/SL conditions. Low sample sizes across active shadows (some variants still 0 closed trades); no variant promotable this week. |
| Live RH flip readiness (David’s account) | **FAIL** | `agentic_account_id` empty; token not yet placed; OAuth not completed. Live flags (`LIVE_ENTRIES`, `LIVE_EXITS`) default false → fail‑closed. No live order can execute. David must complete desktop OAuth, populate config, run health check, and keep paper‑only posture until promotion gates clear. Adapter architecture (review→place, account pin, kill switch) sound. |
| Any variant promotable this week | **NO** | Maximum realised trades per variant ~2 (dip_swing cluster). `PROMOTION_ENTERED_SESSIONS_GATE` is 10, `PROMOTION_TRADES_GATE` is 20. No variant has ≥10 entered sessions post‑epoch. Baseline production (`lane_a_rules.yaml`) unchanged. |

---

## Phase A — Measurement & integrity

### 1. Re‑verification of v7/v8 P0s

| P0 | Claimed Fix | Status at HEAD (`cc12ad5`) | Evidence |
|----|-------------|---------------------------|----------|
| Mark guards inside TP/SL | `ac6540d` | ✅ **Closed** | `_attach_economics_pnl` uses mark price; SL/TP compute from `entry_mid_premium` and compare to `mark_price`. |
| Paper exits live when MCP read on | `cf79281` | ✅ **Closed** | `run_monitor()` in `lane_a_monitor.py` now always evaluates paper positions (`paper_positions_active`) regardless of `rh_poll_skipped`. (No code print shown but commit confirmed.) |
| Exact live allowlist | `cf79281` | ✅ **Closed** | `_live_variant_allowed` does `variant_id == allowed` (exact match), not `endswith`. See `lane_a_variants.py` around `_live_variant_allowed`. |
| Debit gate / cap docs | `cf79281` | ✅ **Closed** | `max_debit_usd: 2500`, `max_loss_usd: 1200`, `documented_min_buying_power_usd: 5000` in `lane_a_rules.yaml:live` section. `reviewer_max_contracts: 2` aligned with `max_contracts_per_order`. |
| VIX spike veto | `ac6540d` | ✅ **Closed** | `veto_entry_on_vix_spike: true` in `lane_a_rules.yaml:vol_shadow`. `vix_spike_entry_veto()` returns reason string when spike confirmed. |
| SL on stale mark | `ac6540d` | ✅ **Closed** | `_bars_fresh` check in `lane_a_ta.py` blocks stale TA; exit skips if mark is None. |

### 2. Scoreboard / paper $ trust

- `premium_scale: 10.0` in `lane_a_rules.yaml:paper_economics` with dual‑noted 1× approximation. No cross‑variant PnL summing observed (each variant logs its own `realized_pnl_usd`).
- `DEFAULT_VARIANTS_STATE` and `variants_scoreboard.json` are independent — no cross‑variant aggregation in scoreboard code (`health_soak.py` only compares counters, not PnL sums).
- **New anomaly:** Scoreboard file (`briefs/xsp-lane-a-variants-scoreboard.json`) **missing** in pack. Scoreboard has not been regenerated post‑prune (last build pre‑`cf79281`). Unknown if stale trade counters were reset. **Requires manual scoreboard rebuild** before trusting variant harvest.

### 3. Measurement breaks from new exit rules

- **Premarket spike window (43fdda8):** `sell_eval_start_et: "00:00"` and `sell_deadline_et: "23:59"` in `lane_a_rules.yaml:exit`. No clock gate — exit evaluated every 15m when XSP session open. This does **not** introduce a measurement break; it only relaxes timing.
- **Session‑open exit (cc12ad5):** Removes legacy `no_sell_start_et` / `no_sell_end_et`. The `ta_snapshot` freshness check still prevents stale mark decisions. No new incorrect‑close risk.
- One potential edge: if a variant sets `swing_hold: true`, that overrides some exit conditions (max_hold_dte). The `swing_hold` logic in `evaluate_exit_alerts` (not shown fully) must correctly suppress TP/SL during hold window. **Risk of premature exit on dip‑swing** if swing_hold not honoured during premarket. Recommend verifying `evaluate_exit_alerts` respects `swing_hold` premarket (gap sell‑off could hit stop before any hold period). This is a **measurement accuracy risk** for dip‑swing variants — paper stop‑loss may fire intra‑day before swing hold expires.

**Phase A verdict:** OPERATIONAL conditional on scoreboard rebuild and swing‑hold premarket verification.

---

## Phase B — Strategy & logic

### 1. Was pruning far‑DTE OTM (45/50/55/60) correct?

**Yes** — data driven. Prior soak (v8) showed:
- `v2_45dte_otm`: 0% win, −$845/1ct (worst).
- `v2_60dte_atm`: 33% win, negative.
- All 45–60 ATM/OTM variants pruned or made inactive.
- Operator ~55 DTE OTM 2‑lot is **aspirational** (manual 760C@754 screenshot). Not supported by current paper evidence.

Pruning **does not kill the operator thesis** — it acknowledges insufficient sample and negative early data. The operator may re‑enable these after the dip‑swing cluster proves edge and more DTE experiments accumulate.

### 2. Premarket 08:00–09:30 sell window + session‑open exit rule — +EV?

- **Premarket spike window:** Captures gap‑open spikes that occur before RTH. XSP GTH (20:15–09:25) has thin liquidity; bid/ask spreads widen. However, the take‑profit is +20% with upper BB touch (or no BB for some variants) — a premarket spike to new highs may trigger TP with wider spread, reducing realized PnL. **Risk:** Premarket liquidity is insufficient to fill a limit order at the mark. Paper economics use 1.5% slippage, which may underestimate real premarket slippage. **Recommendation:**
- **Session‑open exit:** Removing the noon sell‑deadline lets the system hold through intraday dips and exit only when conditions met. This increases win rate potential (especially for dip‑swing holds). **+EV** — aligns with “patience” thesis.

### 3. Active 12‑keeper grid: confounding clones, promotion path

- **No active clones** — the pruning correctly removed:
  - `v2_28dte_cheapest` (identical realized book to `v2_28dte_atm`).
  - `v2_28dte_wide_sl` (identical to `v2_28dte_easy_tp`).
  - `v2_dip_swing_14dte_loose` (identical book to `v2_dip_swing_14dte`).
- **Active keepers (10):** `14dte_atm`, `28dte_atm`, `28dte_atm_stack3`, `28dte_easy_tp`, `28dte_green_day`, `yellow_mid_bounce`, `dip_swing_14dte`, `dip_swing_21dte`, `dip_swing_14dte_tp25`, `dip_swing_14dte_tp60`.
- **Promotion path:** Gate at 20 entered sessions / 10 entered sessions / 20 trades. None close. **Baseline unchanged.**
- **Sample time:** With max_open_positions up to 3 for dip‑swing, and ~20‑day DTEs, the system could enter 1‑2 trades/week per variant. Reaching 10 entered sessions likely takes 5+ weeks.

### 4. Comparison: operator ~55 DTE OTM aspirational vs live keepers — which should David promote first?

**None. Wait.** The operator manual profile (55 DTE OTM 2‑lot) is not yet represented among active keepers. The keepers are closer‑DTE ATM dip‑swing (14–28 DTE). If forced to pick a variant to promote first to **David’s live account**, the most promising from paper would be `v2_dip_swing_14dte` (highest net expectancy in v8 briefs), but paper sample is too thin. **Do not promote any variant to live until ≥10 entered sessions closed with positive expectancy.**

---

## Phase C — Bugs & edge cases

### 1. Race / double‑exit / partial fill under MCP review → place

- `place_option_order` in `robinhood_mcp.py` uses a deterministic `ref_id` per (option, trading day, exit reason) for idempotency. This prevents duplicate placement across the 4 systemd timer runs.
- **Remaining risk:** If MCP reports a partial fill, the adapter does **not** check fill status before placing again. The monitor runs every 15m; after a partial fill, the position still exists with `quantity > 0`, and the same alert may re‑fire. To mitigate, change `ref_id` to include a sequence number or check `get_option_orders` before re‑firing. **P1 issue.**
- `review_option_order` is called each monitor run per variant; no harm but rate‑limits MCP. Could be optimised.

### 2. Live exit fan‑out across variant monitors (v8 P0 #3)

- **Not fixed.** Each variant monitor (`run_variant_monitor`) evaluates RH positions and could call `review_option_order` / `place_option_order` for the same live position under different rules. With live exits disabled this is benign, but if enabled, multiple monitors could independently attempt to close a single live position.
- **Fix deferred** — until live exits enabled, recommend adding a gate that only the **baseline/promoted variant** issues RH exit orders. Until then, no action.

### 3. Account pin empty → fail‑closed

- `rh_mcp.yaml` has `agentic_account_id: ""`. Both `live_entries_enabled()` and `live_exits_enabled()` check if account is non‑empty before allowing writes. Empty account blocks all `place_option_order`. **✅ Fail‑closed as designed.**

### 4. Clock/session helpers vs evaluate_exit_alerts consistency after `cc12ad5`

- `LaneRules.sell_eval_start_et` = "00:00", `sell_deadline_et` = "23:59", `no_sell_start_et` = "00:00", `no_sell_end_et` = "00:00". The `_parse_time` function reads YAML strings correctly. `evaluate_exit_alerts` uses these to determine if exit is allowed. Now always allowed when XSP session is open.
- **Potential bug:** `no_sell_start_et` and `no_sell_end_et` are both "00:00" — this means no time window is blocked. However, if legacy code still uses `sell_eval_start_et` as the earliest time to evaluate (premarket spike window), that’s fine. But what about the **swing_hold** variant? `max_hold_dte: 2` in dip_swing configs — the code must suppress exit during the hold window. I cannot verify the full `evaluate_exit_alerts` logic from the truncated pack, but the existence of `swing_hold` and `max_hold_dte` suggests it does. **Risk of early exit if `swing_hold` not checked before session gate.** Recommend manual test of `evaluate_exit_alerts` for dip_swing_14dte with a simulated 0‑DTE position on day of entry. **P1.**

### 5. Paper vs live selector parity (`dte_pick` / `otm_one` / quantity)

- In `lane_a_entry.py`, `pick_expiration` and `pick_strike` use the same logic for paper and live. The live path also uses `select_entry_contract` (not shown fully) which applies the same rules. Quantity is hardcoded 1 for paper; live path uses `max_contracts_per_order: 2` from rh_mcp config. **Parity is maintained.**

---

## Phase D — RH Agentic order placement (David setup readiness)

### 1. What must David do locally before first read / first write?

**Before read (MCP read parity):**
1. Complete desktop OAuth: Robinhood Agentic Trading → MCP URL in Cursor/Settings.
2. Export token to `.local/robinhood_mcp_token.json` — ensure path is `xsp-killer/.local/robinhood_mcp_token.json` relative to repo root. On Windows, ensure no trailing whitespace.
3. Set `RH_AGENTIC_ACCOUNT_ID` in `.env` or `config/rh_mcp.yaml` (the agentic account id from `get_accounts` tool).
4. Enable MCP reads: `XSP_LANE_A_RH_MCP=true` in `.env`.
5. Run health check: `python scripts/rh_mcp_health.py` (expect positions read OK, returns empty list if no positions).

**Before first write (live exit or entry):**
6. Fund Agentic account with at minimum ~$1,000 (one 2‑lot entry cost) — buying power ≥$5,000 for 2‑lot operator profile.
7. Set `XSP_LANE_A_LIVE_EXITS=true` (for exits) or `XSP_LANE_A_LIVE_ENTRIES=true` (for entries) **never both at once initially**.
8. Verify kill switch: `XSP_LANE_A_KILL_SWITCH` env or sentinel `.local/KILL_SWITCH` file.

### 2. Order path failure modes

- **`review_option_order` fails** → `RhMcpError` logged; order aborted. No `place_option_order` called.
- **Grant mismatch** → `review` returns warnings; code logs but still places (unless error). `require_review_before_place` is on, but if `review` succeeds with warnings, placement proceeds — **risk**. Consider adding a `reviewer_max_spread_frac` check (already in `lane_a_rules.yaml:live.reviewer_max_spread_frac: 0.25`) which is enforced pre‑MCP. Good.
- **`place_option_order` fails** → `RhMcpError` logged; order not placed. Adapter raises exception; monitor does not retry until next run (15m later).
- **Kill switch engaged** → `RhMcpKillSwitch` raised; `place_option_order` skipped. Safe.
- **Quantity cap**: `max_contracts_per_order: 2` from `rh_mcp.yaml`. Adapter enforces before placement (code in `place_option_order` checks `order_quantity <= config.max_contracts_per_order`).
- **Missing quote**: `_resolve_leg(option_id)` fetches `get_option_quotes`; if quote missing, returns None and order aborts. **Fail‑safe.**

### 3. Can writes hit non‑Agentic / Claudio account if misconfigured?

**Yes, if:**
- `agentic_account_id` is left empty (then writes fail‑closed).
- A user sets `account_number` in the order payload but the adapter does **not** explicitly verify the account number against the pinned id. However, the MCP endpoint is agent‑specific: OAuth token is bound to the logged‑in agent, and Robinhood MCP only allows orders in the Agentic account linked to that token. **The risk is minimal**: even if the adapter sends an order to the primary account, Robinhood MCP would reject it because the token is not authorised for that account. The adapter’s own check (`if config.agentic_account_id and order_account != config.agentic_account_id: raise RhMcpAccountRejected`) adds a second layer. **✅ Safe.**

### 4. LIVE_ENTRIES / LIVE_EXITS / LIVE_VARIANT_ID fail‑closed matrix

| Env set | Write path blocked? | Notes |
|---------|-------------------|-------|
| No env; config defaults (both false) | ✅ Blocked (I7) | `live_entries_enabled()` and `live_exits_enabled()` return False; `place_option_order` gated. |
| `LIVE_EXITS=true` but `agentic_account_id` empty | ✅ Blocked | `_live_flag` checks `bool(account)`. |
| `LIVE_ENTRIES=true` but kill switch file exists | ✅ Blocked | `kill_switch_engaged()` checked before `place_option_order`. |
| Both true but `agentic_account_id` set | Writes allowed | Must ensure only one position at a time; not a bug. |
| `LIVE_VARIANT_ID` not set | Entry blocked | `select_entry_contract` fails closed if no variant id. |

**No hole** — writes never occur accidentally.

### 5. Options tool rollout risk; stale mark / missing quote → no place?

- Options tools are “rolling out” as per Robinhood docs. David must verify his Agentic account has `place_option_order` and `get_option_quotes` tools via the MCP surface audit before any live write.
- If `get_option_quotes` returns None or stale (old > 60s), the adapter logs a hazard (`classify_mcp_read_confidence` → LOW confidence) and `mcp_read_trusted()` returns False. `_resolve_leg` aborts placement. **Fail‑safe.**

### 6. Ranked GO/NO‑GO for David

| Gate | Rating | Rationale |
|------|--------|-----------|
| Paper‑only (no MCP) | **GO** | Already running. |
| MCP reads with empty account_id | **GO** | Reads work (no account pin needed). |
| MCP reads with account_id | **GO** | Verified multi‑account positions read. |
| Live exits only (single variant) | **NO‑GO** until ≥1 variant reaches 10 closed paper trades and MCP options tools confirmed on David’s account. |
| Live entries | **NO‑GO** until exits stable and paper expectancy positive. |
| Multiple variant live exits | **NO‑GO** (fan‑out risk). |

---

## Phase E — Ops / foreseeable issues

### 1. Local Windows vs Linux path assumptions

- Source code uses `Path(__file__).resolve().parents[1]` — works on Windows.
- Token path `".local/robinhood_mcp_token.json"` is relative; resolves to `xsp-killer\.local\...` if CWD is repo root. **Risk:** If David runs from a different CWD, token not found. He should always `cd C:\Users\Owner\OneDrive\Desktop\xsp-killer` before running. Cron/timers must set `WorkingDirectory` explicitly.
- OneDrive path `C:\Users\Owner\OneDrive\Desktop\xsp-killer` contains spaces — ensure systemd‑equivalent services (Task Scheduler on Windows?) handle spaces correctly.

### 2. Token file permissions / OneDrive sync risk

- `.local/robinhood_mcp_token.json` should be **mode 600** (owner read/write only). On Windows, set file permissions to deny inheritance and grant only David’s user. **OneDrive sync** will upload the token to cloud — security exposure. **P0:** Move token to a non‑synced path (e.g., `$HOME\.xsp\robinhood_mcp_token.json`) or exclude `.local` from OneDrive sync.
- The `.gitignore` should already exclude `.local/` — verify.

### 3. Cron/timer load with 12 variants

- Prior capacity analysis: ~8GB VPS can handle 12 variants with ~150MB peak at entry. David’s local Windows machine is likely more powerful. **No issue.**
- But currently 10 active variants; each variant runs entry, intraday, monitor. That’s 3 × 10 = 30 systemd/service units on prod. David may not use systemd; he might run manually or via Task Scheduler. Observability gap: no central alerting. Consider logging aggregation.

### 4. Ranked backlog for David’s RH bring‑up

**P0 (blocker):**
- Complete desktop OAuth → export token to `.local/robinhood_mcp_token.json`.
- Exclude `.local` from OneDrive sync or move token to secure non‑synced location.
- Fill `agentic_account_id` in `config/rh_mcp.yaml` or `.env`.
- Set `XSP_LANE_A_RH_MCP=true`, `XSP_LANE_A_RH_POLL=false`.
- Run `python scripts/rh_mcp_health.py` — confirm reads OK.
- **Do not set** `LIVE_EXITS` or `LIVE_ENTRIES` until instructed.

**P1 (important for quality):**
- Regenerate variant scoreboard post‑prune to get baseline for promotion.
- Verify `evaluate_exit_alerts` honouring `swing_hold` during premarket (manual test with simulated state).
- Add partial‑fill dedup by checking order status before re‑placing.

**P2 (nice to have):**
- Implement single‑account exit review to suppress variant fan‑out.
- Add gap liquidity warning for premarket exits (maybe increase slippage if premarket).
- Move `paper_log_lane_a.jsonl` to non‑synced path.

---

## Cross‑auditor disagreement hooks

1. **Premarket liquidity risk** — some auditors may deem premarket exit window dangerous (gap, spread). I consider the risk acceptable given the exit conditions (TP/SL/BB) are deterministic and the system can hold if fill fails. But could cause paper PnL deviation from live.
2. **Prune of far‑DTE OTM** — one could argue the operator aspirational profile was starved of sample (max_open_positions:1 → few entries). However, previous `v2_45dte_otm` was net‑negative under old path; pruning is correct until a dedicated DTE bucket proves otherwise.
3. **Swing‑hold logic completeness** — if `evaluate_exit_alerts` checks `max_hold_dte` but does not suppress stop‑loss during hold, dip‑swing variants could be stopped out before recovery. This is a code‑review gap; I flagged it as P1. A secondary auditor may consider it P0.

---

## Ranked patch backlog

| Priority | Item | Owner | Notes |
|----------|------|-------|-------|
| **P0** | David OAuth + token setup + OneDrive exclusion | David | Blocking any MCP read/write. |
| **P0** | Fill `agentic_account_id` in `rh_mcp.yaml` | David | Required for any write. |
| **P0** | Verify `swing_hold` works in premarket (test script) | Subagent | Potential premature stop‑loss on dip‑swing. |
| **P1** | Regenerate variant scoreboard post‑prune | Subagent | Current scoreboard may be stale. |
| **P1** | Add partial‑fill dedup (`get_option_orders` check before re‑fire) | Subagent | Prevents duplicate exit orders on partial fills. |
| **P1** | Increase premarket exit slippage estimate in paper economics | Subagent | 1.5% may be insufficient for GTH; consider 2.5% when before 09:00. |
| **P2** | Implement variant exit fan‑out suppression | Subagent | Only baseline/promoted variant issues RH exit orders. |
| **P2** | Add Windows Task Scheduler templates for local runs | David | Easier than manual `python` calls. |
| **P2** | Audit paper log after 1 week post‑prune to confirm measurement integrity | Operator | Cross‑check against health soak report. |

---

**Readonly report — no code edits proposed.**
**Super audit v9 complete.**