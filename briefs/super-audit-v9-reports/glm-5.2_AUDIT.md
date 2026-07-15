# cursor-audit · glm-5.2-openrouter · xsp-killer · SUPER AUDIT v9

**Auditor:** glm-5.2-openrouter · **HEAD audited:** `cc12ad5` · **Mode:** prod-ship readonly
**Prior round:** v8 synthesis (`e6bb155` → `cf79281` fixes) · **Pack built:** 2026-07-15T16:30Z

---

### Executive verdict

1. **Paper soak / measurement integrity — WARN.** v8 P0 fixes appear landed in code (`cf79281`), but the pack is missing `variants_scoreboard.json`, `paper_log_lane_a.jsonl`, and `entry_telemetry_latest.json`; `pytest` exits non-zero at HEAD. Cannot confirm any post-epoch soak data exists. The 10× premium-scale paper-$ overstatement (documented but not resolved for absolute-$ trust) carries forward.

2. **Strategy coherence (prune + exit timing) — WARN.** Pruning far-DTE OTM (45–60) was evidence-based *under the old morning-cut exit regime*, but `cc12ad5` (session-open exit) + `43fdda8` (premarket spike window) fundamentally change exit dynamics — the operator's ~55 DTE OTM thesis was never re-tested under the new regime. Active dip-swing grid is highly correlated and sample-starved (≥20-trade gate unreachable for months).

3. **Live RH flip readiness (David's account) — FAIL.** `agentic_account_id` empty; David's OAuth not connected; Windows path/scheduler unresolved; token file inside OneDrive-synced folder (upload risk); variant exit fan-out (v8 P0 #3) still latent; `pytest` red. No live placement should occur.

4. **Is any variant promotable this week? — NO.** No `edge_confirmed` variant; scoreboard missing (cannot verify trade counts); no closed paper trade confirmed post-epoch under new exit logic. Keep `LIVE_ENTRIES=false` / `LIVE_EXITS=false`.

---

### Phase A — Measurement

**A1. v7/v8 P0 regression matrix at `cc12ad5`**

| v7/v8 P0 | Status | Evidence |
|----------|--------|----------|
| Mark guards inside TP/SL (`ac6540d`) | ✅ claimed closed | `lane_a_monitor.py` `LaneAPosition.mark_quote_stale` field + `_attach_economics_pnl`; stale-mark guard referenced in `evaluate_exit_alerts` path (code truncated — verify) |
| Paper exits dead when RH MCP on (v8 P0 #0, `cf79281`) | ✅ claimed closed | Runbook Phase 1: "Lane A monitor calls `review_option_order` on exit signals when MCP is enabled"; `rh_poll_skipped` no longer sole gate for paper positions. Full `run_monitor` body truncated — **cannot fully verify** paper-position refresh path when `XSP_LANE_A_RH_MCP=true` |
| Live allowlist exact match (v8 P0 #2, `cf79281`) | ✅ claimed closed | `_live_variant_allowed` not visible in truncated source; runbook says "exact match only on `variant_id`/`logic_version`" — verify no `endswith` remains |
| `max_debit_usd` gate (v8 P0 #1) | ✅ present | `lane_a_rules.yaml` `live.max_debit_usd: 2500.0`, `documented_min_buying_power_usd: 5000`, `max_cost_frac: 0.5`, `reviewer_max_contracts: 2` aligned with `rh_mcp.yaml` `max_contracts_per_order: 2` |
| VIX spike veto (`ac6540d`) | ✅ present | `vol_monitor.py` `vix_spike_entry_veto()`; `lane_a_rules.yaml` `vol_shadow.veto_entry_on_vix_spike: true` |
| SL on stale mark | ✅ claimed closed | `mark_quote_stale` field on `LaneAPosition`; stale guard in exit eval (verify body) |

**A2. Scoreboard / paper-$ trust**

- `premium_scale: 10.0` in `lane_a_rules.yaml`; `paper_economics.py` `dual_notional_from_spy_mid()` logs both `mark_xsp_scaled` (10×) and `mark_xsp_alt_1x` (1×). % TP/SL are scale-invariant. **But** the 10× absolute-$ paper PnL overstates real XSP by ~10× (XSP ≈ SPY per-share premium, 1×, per the config comment). The scoreboard's `*_1x_approx` field is the trustworthy real-dollar column. **Do not sum PnL across variants** — they share correlated entries.
- **CRITICAL:** `variants_scoreboard.json` is **missing** from the pack (`C:\Users\Owner\OneDrive\Desktop\xsp-killer\briefs\xsp-lane-a-variants-scoreboard.json` not found). `paper_log_lane_a.jsonl` missing. `entry_telemetry_latest.json` missing. **No soak data is verifiable.** v8 said "0 closed trades" for dip-swing cluster — cannot confirm any change.
- `pytest_results.txt`: `Command [...] returned non-zero exit status 1.` **Tests are red at HEAD.** Likely `cc12ad5` (zeroed `no_sell` window, `sell_eval_start: "00:00"`) broke clock-dependent exit tests. This is a measurement-integrity P0 — cannot trust code behavior if tests don't pass.

**A3. New measurement breaks from premarket-spike / session-open exit**

- `lane_a_rules.yaml` exit: `sell_eval_start_et: "00:00"`, `sell_deadline_et: "23:59"`, `no_sell_*: "00:00"`. Comment: "evaluate_exit_alerts ignores them." Exit now fires whenever XSP session is open (GTH 20:15–09:25, RTH 09:30–16:15, curb 16:15–17:00 ET).
- **GTH slippage understatement:** Paper economics caps slippage at 1.5% of premium (`slippage_max_pct_of_premium: 0.015`). XSP GTH bid-ask spreads routinely 5–15% of mid. A premarket (08:00–09:30) exit at "mark" with 1.5% slippage **materially overstates** achievable fill. Paper PnL on GTH exits is optimistic vs live.
- **Stale-mark risk during GTH:** If `get_option_quotes` returns a wide-but-present quote (not "stale"), `mark_quote_stale` may be False, and SL/TP fires on a misleading mid. The guard catches *absent* marks, not *wide* marks. The `reviewer_max_spread_frac: 0.25` veto on the live path mitigates placement, but paper exits don't use the reviewer — they trust the mark.
- **Session-gate fragility:** `evaluate_exit_alerts` ignores clock windows per `cc12ad5`; session-open check is at the cron/script level ("no-ops if closed"). A manual off-session monitor run would evaluate exits on stale marks with only the stale-guard as backstop. Acceptable for cron, fragile for manual ops.

---

### Phase B — Strategy & logic

**B1. Was pruning far-DTE OTM (45–60 DTE) correct or premature?**

**Defensible but untested under the new exit regime.** Evidence at prune time (`ea4ea58`/`f3b57ac`): `v2_45dte_otm` was "worst in soak (0% win, -$845/1ct)"; `v2_45dte_atm` "net-negative (33% win, -$457/1ct)"; `v2_60dte_atm` "net-negative (33% win, -$281/1ct)." **But** those results were under the *old* exit path: morning `time_stop` at 10:00 ET, clock-gated sell window, no premarket spike capture. The operator's ~55 DTE OTM thesis is *hold for recovery, sell into strength* — which is exactly what `cc12ad5` (session-open exit) + `43fdda8` (premarket spike window) enable. The prune removed the variants **before** the new exit logic could re-validate them. The old negative verdict may not hold under the new regime. **Recommend:** re-enable one `v2_dip_swing_55dte_otm` shadow variant before declaring the operator aspirational thesis dead.

**B2. Premarket 08:00–09:30 sell window + session-open exit — +EV for dip-swing?**

- **Directionally +EV:** Dip-swing variants (`TP +40%/+25%/+60%`, `SL -50%`) benefit from capturing overnight recovery spikes. Selling into GTH strength when TP hits is logically sound — the alternative (waiting for RTH 09:30) risks giving back the gap.
- **Gap/liquidity risk on XSP:** XSP GTH volume is a fraction of RTH. Spreads widen materially 20:15–09:25 ET. A +40% TP that "hits" on a thin GTH mid may fill at +25% or worse live. Paper (1.5% slippage cap) won't reflect this. The `reviewer_max_spread_frac: 0.25` live veto would block placement if spread > 25% — but that means **live exits may skip when paper exits fire**, creating paper/live divergence.
- **Monitor cadence:** 15-minute polls (`et_check_minutes: [0,15,30,45]`). A fast premarket spike (common: 5-min pop and fade) can be missed entirely. The paper exit may record a fill at a mark that the 15m poll never actually observed in real time.
- **Net:** +EV thesis, overstated paper confidence. Treat paper premarket exits as upper-bound.

**B3. Active 12-keeper grid: confounding, promotion path, sample time**

Active variants visible in `lane_a_variants.yaml` (10 confirmed, ~2 more in truncated tail — likely a spread variant + one more):

| Variant | Entry | Exit | Notes |
|---------|-------|------|-------|
| `v2_14dte_atm` | 14 DTE ATM, close-window | TP20/SL20 no BB | Baseline short-gamma |
| `v2_28dte_atm` | 28 DTE ATM | TP20/SL20 no BB | Less gamma |
| `v2_28dte_atm_stack3` | 28 DTE ATM, 3 pos | TP20/SL20 no BB | Throughput |
| `v2_28dte_easy_tp` | 28 DTE ATM | TP10/SL20 no BB | Quick scalp |
| `v2_28dte_green_day` | 28 DTE ATM, prior-green | TP20/SL20 no BB | Tape filter |
| `v2_yellow_mid_bounce` | 28 DTE ATM, YELLOW≥0.50 | TP20/SL20 no BB | Regime axis |
| `v2_dip_swing_14dte` | 14 DTE ATM, DIP_BOUNCE | TP40/SL50 swing | Core dip-swing |
| `v2_dip_swing_21dte` | 21 DTE ATM, DIP_BOUNCE | TP40/SL50 swing | Runway axis |
| `v2_dip_swing_14dte_tp25` | 14 DTE ATM, DIP_BOUNCE | TP25/SL50 swing | Fast scalp |
| `v2_dip_swing_14dte_tp60` | 14 DTE ATM, DIP_BOUNCE | TP60/SL50 swing | Let winners run |

- **Confounding / clones:** Prune comments correctly identified clones (`v2_28dte_cheapest` = `v2_28dte_atm`; `v2_dip_swing_14dte_loose` = `v2_dip_swing_14dte`). Good hygiene. Remaining dip-swing trio (`tp25`/`tp40`/`tp60`) shares **identical entry logic** — they enter on the same BB-bounce + VWAP-reclaim signal. With `max_open_positions: 3`, all three can fill the same dip. Their PnL is **highly correlated**; distinguishing TP25 vs TP40 vs TP60 requires many independent dips. Not confounding (different exit rules), but **sample-inefficient**.
- **Promotion path:** `PROMOTION_SESSIONS_GATE=20`, `PROMOTION_ENTERED_SESSIONS_GATE=10`, `PROMOTION_TRADES_GATE=20` (`lane_a_variants.py`). Dip-bounce entries (intraday BB bounce + VWAP reclaim in any regime) are rare — maybe 1–3/month. 20 trades → 7–20 months. The entered-sessions gate (10) binds first. **Sample time is the binding constraint**, not capacity.
- **No variant is near promotion** — scoreboard missing, but v8 confirmed 0 closed dip-swing trades. Even if exits now work post-`cf79281`, the clock just restarted.

**B4. Operator ~55 DTE OTM 2-lot aspirational vs live keepers — which should David promote first?**

**Neither.** No variant has proven edge. But if David wants to eventually trade his aspirational profile (760C ~55 DTE, matching the screenshot):

- The live keepers (14–28 DTE ATM dip-swing) are **closer to proof** (active, collecting data) but test a different thesis (short-gamma dip-bounce, not long-vega recovery).
- The 55 DTE OTM profile is **pruned and untested under new exits**. It aligns better with the new session-open/premarket-spike exit logic (sell into recovery) than the old regime that pruned it.
- **Recommendation:** David should **not promote anything to his RH this week.** First, re-enable one `v2_dip_swing_55dte_otm` shadow variant to collect data under the new exit regime. If after ≥20 sessions it shows edge, it becomes the promotion candidate — not the 14 DTE ATM keepers. The operator aspirational profile and the active soak grid are currently **disjoint**; bridging them requires re-activating the pruned thesis.

---

### Phase C — Bugs & edge cases

**C1. Race / double-exit / partial fill under RH MCP `review` → `place`**

- **Double-exit:** Idempotent per `(option, trading day, exit reason)` via deterministic `ref_id` (runbook Phase 2). Good. The 4 morning runs cannot duplicate an exit. ✅
- **Partial fill:** If `place_option_order` fills 1 of 2 contracts, the `ref_id` dedup blocks retry of the remaining 1. No visible partial-fill reconciliation path (re-read `get_option_orders`, place residual). `cancel_option_order` exists but only for unfilled. **WARN** — partial fills leave residual position unmanaged until next 15m cycle, and the dedup may prevent re-exit if the exit reason matches.
- **Race:** `_variants_rmw_lock` (fcntl) guards variant state file; `_state_lock` guards baseline state. Good for paper. For live MCP writes, no visible cross-process lock around `review → place` — two monitor processes (baseline + variant) could both review the same RH position. See C2.

**C2. Live exit fan-out across variant monitors (v8 P0 #3)**

- **Still latent.** v8 deferred as P1 "if live exits stay off." `run_all_variant_monitors` calls `run_monitor` for each active variant. If `LIVE_EXITS=true`, each variant monitor could call `review_option_order` / `place_option_order` on the **same real RH position** under different TP/SL rules. One variant's TP40 fires while another's TP60 holds — conflict.
- The runbook Phase 2 describes a singular "the monitor" auto-placing exits, but `run_all_variant_monitors` runs 12 monitors. **No visible guard** skipping RH MCP writes on variant-monitor passes (baseline/promoted variant only). **P0 the moment `LIVE_EXITS=true` is considered.** Currently safe because `live_exits: false`.

**C3. Account pin empty → fail-closed?**

- ✅ **Yes.** `robinhood_mcp.py` `_live_flag()`: returns `bool(account)` — if `RH_AGENTIC_ACCOUNT_ID` unset and `agentic_account_id: ""`, `live_exits_enabled()` and `live_entries_enabled()` return False. `place_option_order` cannot proceed. Verified fail-closed.

**C4. Clock/session helpers vs `evaluate_exit_alerts` consistency after `cc12ad5`**

- `lane_a_rules.yaml` exit fields zeroed (`sell_eval_start: "00:00"`, `no_sell: "00:00"`); comment says `evaluate_exit_alerts` ignores them. Commit `cc12ad5`: "remove clock sell/no-sell gate from evaluation."
- `LaneRules` dataclass still parses these fields (backward compat for shadow bracket). No inconsistency in parsing.
- **Session-open gate:** Commit message says "whenever XSP session is open" — implies a session check remains in or around `evaluate_exit_alerts`. The monitor cron "no-ops if closed" (config comment). **Cannot verify** the session helper (GTH/RTH/curb boundaries) from truncated source. If the session check is only at the script level (not in `evaluate_exit_alerts`), a manual off-session call evaluates on stale marks. **WARN** — verify session gate is inside `evaluate_exit_alerts` or its caller, not just the cron wrapper.
- **Test breakage:** `pytest` red at HEAD. Likely the zeroed clock fields broke tests asserting old 09:30–10:00 behavior. **P0** — fix tests or the exit logic is unverified.

**C5. Paper vs live selector parity (`dte_pick` / `otm_one` / quantity)**

- `pick_strike()` handles `atm_only`, `otm_one` (atm + 5.0), `cheapest_near_atm`. `pick_expiration()` handles `min`/`max`/`target`. Live path uses `select_entry_contract` (not fully visible). v8 claimed closed in `ac6540d`. `otm_one` uses `atm + 5.0` (one XSP $5 strike step) — correct for XSP, avoids the old `round(750.5)→750` half-step collapse. ✅ claimed fixed; verify `select_entry_contract` calls the same `pick_strike`/`pick_expiration`.

---

### Phase D — RH Agentic order placement (David setup readiness)

**D1. What must David do locally before first read / first write?**

**Before first read:**
1. Complete desktop OAuth: Cursor → Settings → Tools & MCP → connect `https://agent.robinhood.com/mcp/trading` → Robinhood login in browser (desktop required). Or Claude Code `claude mcp add`.
2. Open Agentic account in Robinhood app (if not already). Fund later.
3. Export token to `.local/robinhood_mcp_token.json` (JSON with `access_token`). **Place outside OneDrive sync** (see E2).
4. Set `XSP_LANE_A_RH_MCP=true` in `.env` (keep `XSP_LANE_A_RH_POLL=false`).
5. Run `python scripts/rh_mcp_health.py` — expect MCP positions read (or empty list).
6. Tool-surface audit: confirm `get_option_positions`, `get_option_quotes`, `review_option_order`, `place_option_order` exist on David's account. Record in `config/rh_mcp_audit.md`.

**Before first write:**
1. Pin `RH_AGENTIC_ACCOUNT_ID` in `.env` (David's Agentic account number from `get_accounts`).
2. Fund Agentic account (≥ one contract cost; real XSP ~$245/contract at 1× SPY scale, so ~$500 minimum for 2-lot; `documented_min_buying_power_usd: 5000` is conservative).
3. Set `XSP_LANE_A_LIVE_EXITS=true` (exits first) or `XSP_LANE_A_LIVE_ENTRIES=true` (entries later) in the service env.
4. Clear kill switch: `XSP_LANE_A_KILL_SWITCH` unset, no `.local/KILL_SWITCH` file.
5. Single-contract test sell (exit) or test buy (entry); confirm Robinhood push notification.
6. Rollback drill: set flag false + disconnect agent in Robinhood app (≤60s).

**D2. Order path: `review_option_order` → grant match → `place_option_order` — failure modes, kill switches, quantity caps**

- **Path:** `require_review_before_place: true` (config) → `review_option_order` returns warnings → `shadow_review_order` (K37 fail-open reviewer) checks `reviewer_max_spread_frac: 0.25` (veto if `(ask-bid)/mid > 25%`) and `reviewer_max_contracts: 2` → grant match via `_review_grant_key` → `place_option_order`.
- **Failure modes:**
  - Spread too wide → reviewer veto → no place (safe).
  - BP insufficient → `get_portfolio` gate → skip (fail-safe, not error).
  - Account mismatch → `RhMcpAccountRejected` exception.
  - Kill switch → `RhMcpKillSwitch` exception; cancels still allowed.
  - Token expired → `RhMcpNotReady` → no network call.
  - MCP returns non-JSON/SSE parse fail → `RhMcpError`.
- **Kill switches:** `XSP_LANE_A_KILL_SWITCH` env / `.local/KILL_SWITCH` sentinel file (blocks all `place_option_order`, allows `cancel_option_order`); `LIVE_ENTRIES=false` (blocks opens); `LIVE_EXITS=false` (blocks closes); Robinhood app disconnect (revokes OAuth). ✅ layered.
- **Quantity caps:** `rh_mcp.yaml` `max_contracts_per_order: 2`; `lane_a_rules.yaml` `reviewer_max_contracts: 2`. Aligned. ✅

**D3. Can writes ever hit a non-Agentic / Claudio account if misconfigured?**

- **Primary control (Robinhood-side):** MCP `place_option_order` can only trade the **Agentic account** tied to the OAuth token. Primary/legacy accounts are read-only for order placement. So even if `RH_AGENTIC_ACCOUNT_ID` is wrong, writes go to whichever Agentic account the token belongs to.
- **Secondary control (adapter-side):** `RhMcpAccountRejected` if order `account_number` ≠ pinned `agentic_account_id`. But the pin is whatever `RH_AGENTIC_ACCOUNT_ID` says — if David accidentally uses Claudio's token file + Claudio's account ID, it trades Claudio's Agentic account.
- **Claudio coupling risk:** `rh_mcp_connection_brief.md` targets "cemini-prod `/opt/xsp-killer`" and references Claudio's credentials. If David copies the cemini-prod `.env` (with a stale `RH_AGENTIC_ACCOUNT_ID` pointing to Claudio's account) and reuses Claudio's token, writes hit Claudio's Agentic account. **David must verify the token file and account ID are HIS, not inherited from cemini-prod.** The config file `agentic_account_id: ""` is empty (good default), but env override is the risk.
- **Verdict:** Cannot hit a non-Agentic account (Robinhood enforces). Can hit the *wrong* Agentic account if David reuses Claudio's token/env. Token-file isolation is the real control.

**D4. LIVE_ENTRIES / LIVE_EXITS / LIVE_VARIANT_ID fail-closed matrix**

| Flag state | Opens (buy-to-open) | Closes (sell-to-close) | Hole? |
|------------|---------------------|------------------------|-------|
| All false (default) | Blocked | Blocked | ✅ safe |
| `LIVE_EXITS=true`, entries off, account pinned | Blocked | Allowed | ⚠️ Baseline monitor can exit a real RH position even with no `LIVE_VARIANT_ID` set — exits whatever it sees per `lane_a_rules.yaml` baseline rules. If David manually holds a position entered under different variant rules, baseline exits it. Feature or hole depending on intent. |
| `LIVE_ENTRIES=true`, `LIVE_VARIANT_ID` unset | Blocked (fail-closed) | — | ✅ safe |
| `LIVE_ENTRIES=true`, `LIVE_VARIANT_ID` set to **pruned/inactive** variant | ⚠️ If allowlist only checks string match (not `active` flag), entry could fire with a pruned variant's rules | — | **P1** — verify `_live_variant_allowed` also checks `active: true` in `lane_a_variants.yaml`, not just exact string match |
| Kill switch on | Blocked | Blocked (cancels allowed) | ✅ safe |
| Account empty | Blocked | Blocked | ✅ safe (`_live_flag` returns False) |

**Hole summary:** (1) Live exits without a promoted variant can act on manually-held positions under baseline rules — document or gate. (2) Inactive-variant allowlist check unverified. (3) Variant fan-out (C2) if `LIVE_EXITS=true` with 12 monitors running.

**D5. Options tool rollout risk; stale mark / missing quote → no place?**

- **Rollout risk:** Robinhood docs say options "rolling out" (brief, 2026-06-29). David must verify `place_option_order` appears in his tool surface before any live flip. If options tools aren't enabled on his Agentic account, all writes fail with `RhMcpError` — safe but blocking.
- **Stale mark → no place:** `evaluate_exit_alerts` should skip exit if `mark_quote_stale`. On the live path, `review_option_order` + `reviewer_max_spread_frac: 0.25` vetoes wide spreads. If `get_option_quotes` returns missing quote (not stale), the reviewer has no mid → should veto. **Verify** the code path: missing quote → no mark → no limit price → no `place_option_order`. Not fully visible in truncated source. **WARN.**

**D6. Ranked GO/NO-GO**

| Stage | Verdict | Conditions |
|-------|---------|------------|
| Paper-only | **GO** | Current state. Safe. But fix `pytest` red first. |
| MCP reads | **GO (conditional)** | After David's OAuth + token outside OneDrive + `rh_mcp_health.py` passes + tool audit confirms read tools. |
| Live exits only | **NO-GO** | Until: (a) ≥1 closed paper trade post-epoch confirmed in scoreboard; (b) `pytest` green; (c) variant fan-out fix (C2) — variant monitors skip RH MCP writes; (d) partial-fill handling (C1); (e) David's account pinned + funded; (f) tool audit confirms `place_option_order`. |
| Live entries | **NO-GO** | All of the above + `edge_confirmed` on a variant (≥20 trades, positive expectancy) + `LIVE_VARIANT_ID` set to an **active** variant + BP funded ($5k documented). |

---

### Phase E — Foreseeable ops issues

**E1. Local Windows vs `/opt/xsp-killer` Linux path assumptions**

- Code uses `ROOT = Path(__file__).resolve().parents[1]` — portable. ✅
- `systemd/*.service` + `*.timer` units are Linux-only. David on Windows needs **Task Scheduler** or **WSL**. The runbook and briefs reference `/opt/xsp-killer` and systemd exclusively — **no Windows scheduler documentation exists.** P1.
- `fcntl` file locking (`_state_lock`, `_variants_rmw_lock`) is Unix-only. On native Windows Python, `fcntl` import fails. **David must use WSL** or the locks break (the code catches `OSError` and proceeds unlocked for `_variants_rmw_lock`, but `_state_lock` does not catch import failure). **P1** — if David runs native Windows, `import fcntl` at module top of `lane_a_monitor.py` crashes on import.

**E2. Token file permissions / OneDrive sync risk for `.local/`**

- **P0 for David's setup.** Repo is at `C:\Users\Owner\OneDrive\Desktop\xsp-killer`. `.local/robinhood_mcp_token.json` is inside the OneDrive-synced folder. **OneDrive will upload the token to the cloud** — a credential exposure risk. `.gitignore` excludes it from git, but OneDrive sync is independent.
- **Fix:** Place token at an absolute path outside OneDrive (e.g., `C:\Users\David\.xsp-killer\robinhood_mcp_token.json`) and set `token_path` in `config/rh_mcp.yaml` to that absolute path. Or exclude `.local/` from OneDrive sync.
- Runbook says "mode 600, root-only" — irrelevant on Windows; Windows ACLs are the control. Document Windows permissions.

**E3. Cron/timer load with 12 variants; observability gaps**

- **Load:** Runbook says ~12 variants ≈ 30s + ~150MB peak at 15:45 entry. Intraday: 12 variants × 15m polls × ~6.5h RTH + GTH = ~300+ variant evaluations/day. `fetch_intraday_bars` is cached 120s per (symbol, timeframe) — shared across variants. Acceptable on VPS; on David's Windows machine, Task Scheduler overhead + Python startup per invocation could be slow. Consider a long-running daemon instead of per-cron-spawn on Windows.
- **Observability gaps:** `logs/rh_mcp_audit.jsonl` (MCP calls), per-variant `logs/xsp_lane_a_variant_*.jsonl`, `logs/xsp_lane_a_paper.jsonl`. No centralized alerting on Windows (no systemd journal, no Discord/Telegram webhook visible). David won't get push notifications for paper anomalies — only live RH trades trigger Robinhood push. **P2** — add a health-check alerting path for Windows.
- **Log rotation:** Not visible. `paper_log_lane_a.jsonl` + 12 variant logs grow unbounded. **P2.**

**E4. Ranked P0/P1/P2 backlog for David's RH bring-up**

| Priority | Item |
|----------|------|
| **P0** | Fix `pytest` red at HEAD (`cc12ad5` broke clock/session tests) — no live flip with red tests |
| **P0** | Move OAuth token outside OneDrive sync; set absolute `token_path` in `config/rh_mcp.yaml` |
| **P0** | Verify David's `.env` has **his** `RH_AGENTIC_ACCOUNT_ID` (not Claudio's); no inherited cemini-prod credentials |
| **P0** | Confirm `variants_scoreboard.json` regenerates with post-epoch data (currently missing) — cannot assess soak without it |
| **P1** | Windows runtime: WSL (for `fcntl`) or port file locks; Task Scheduler/daemon for 15m cadence; document Windows bring-up |
| **P1** | Variant exit fan-out fix (C2): variant monitors must skip RH MCP writes; only baseline/promoted variant reviews real positions |
| **P1** | Partial-fill reconciliation (C1): re-read `get_option_orders`, place residual after partial fill |
| **P1** | Verify `_live_variant_allowed` checks `active: true` (not just exact string match) — blocks promoting pruned variants |
| **P1** | Verify session-open gate is inside `evaluate_exit_alerts` or caller (not just cron wrapper) — prevents off-session stale-mark exits |
| **P1** | Re-enable one `v2_dip_swing_55dte_otm` shadow to test operator thesis under new exit regime |
| **P2** | GTH slippage model: raise paper slippage cap for premarket exits or flag GTH exits as "optimistic" in scoreboard |
| **P2** | Log rotation for paper + variant + MCP audit logs |
| **P2** | Windows observability: health-check alerting (webhook/email) for paper anomalies |
| **P2** | Calibrate live gates to real 1× XSP premiums (`max_debit_usd: 2500` never binds on ~$490 real 2-lot; `max_loss_usd: 1200` never binds on ~$245 real max loss) — safe but loose; document real-$ risk |

---

### Cross-auditor disagreement hooks

1. **Far-DTE OTM prune verdict.** Other auditors may treat the prune (`ea4ea58`) as final given the old negative soak data. I argue the prune removed the operator's aspirational thesis *before* the new exit regime (`cc12ad5` session-open + `43fdda8` premarket spike) could re-validate it. The old results (morning `time_stop`, clock-gated sells) don't apply to "hold for recovery, sell into strength." Re-test one 55 DTE OTM dip-swing shadow before declaring the thesis dead.

2. **Premarket GTH exit +EV assessment.** Other auditors may rate the 08:00–09:30 spike window as clearly +EV (capture the pop). I flag that XSP GTH spreads (5–15% of mid) vs paper slippage cap (1.5%) means paper PnL on premarket exits is materially optimistic, and the 15-minute poll cadence can miss fast spikes entirely. Paper premarket exits are an upper bound, not a forecast.

3. **Paper-soak rating.** Other auditors may rate paper soak as OPERATIONAL based on code review (v8 P0s fixed). I rate it WARN because the actual soak artifacts (`variants_scoreboard.json`, `paper_log_lane_a.jsonl`, `entry_telemetry_latest.json`) are **missing from the pack** and `pytest` is **red** at HEAD. Code-correct ≠ data-trustworthy; we cannot confirm a single post-epoch closed trade exists under the new exit logic.

---

### Ranked patch backlog

**P0 (blockers — before any further soak trust or live readiness)**

1. Fix `pytest` red at HEAD `cc12ad5` — zeroed `no_sell`/`sell_eval_start` fields broke clock-dependent exit tests; exit logic is unverified while tests fail.
2. Regenerate `variants_scoreboard.json` — currently missing; no soak data is verifiable. Confirm post-epoch trades exist under new exit regime.
3. David's token file outside OneDrive sync — credential exposure risk on Windows.
4. Verify David's `.env` account ID is his own (not Claudio's cemini-prod inherited credential).

**P1 (before live exits or trustworthy variant rank)**

5. Variant exit fan-out fix — variant monitors skip RH MCP writes; only baseline/promoted variant reviews real positions (v8 P0 #3, still latent).
6. Partial-fill reconciliation after `place_option_order` — re-read orders, place residual.
7. Verify `_live_variant_allowed` checks `active: true` in addition to exact string match.
8. Verify session-open gate inside `evaluate_exit_alerts` (not just cron wrapper) — prevent off-session stale-mark evaluation.
9. Windows runtime path: WSL for `fcntl` or port locks; Task Scheduler/daemon + Windows bring-up doc.
10. Re-enable one `v2_dip_swing_55dte_otm` shadow variant to test operator thesis under new exits.

**P2 (calibration / observability)**

11. GTH slippage model — raise paper slippage for premarket exits or flag as optimistic in scoreboard.
12. Calibrate live gates to real 1× XSP premiums (current gates are loose on real ~$245/contract premiums; document real-$ risk).
13. Log rotation for paper + variant + MCP audit logs.
14. Windows observability — health-check alerting for paper anomalies.

---

*Readonly recommendations only — no code edits. Auditor glm-5.2-openrouter, XSP Killer super-audit v9, HEAD `cc12ad5`.*