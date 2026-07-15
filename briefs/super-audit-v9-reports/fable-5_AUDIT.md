# cursor-audit · fable-5 · xsp-killer · SUPER AUDIT v9

**Auditor slot:** claude-fable-5-thinking-high (agentic-reasoning) · **Mode:** prod-ship, readonly
**HEAD under audit:** `cc12ad5` (per pack `xsp_git_log.txt`) · **Pack:** `reports/gap-audit/pack-xsp-killer-v9/`
**Date:** 2026-07-15

## Executive verdict

1. **Paper soak / measurement integrity — WARN.** The v8 P0 code fixes (`cf79281`) are verifiably in HEAD, but **this v9 pack contains zero runtime evidence** — every soak artifact resolves to `(missing: …)` because the pack was built on the Windows workspace while the soak lives on the VPS (`briefs/`, `logs/` empty here; `pytest_results.txt` = "command failed: python3 not found"). Soak numbers, promotion gates, and the effect of the prune are unverifiable from this pack. Additionally: paper-book exit evaluation silently starves once a *real* RH position exists (`lane_a_monitor.py:1206`), paper GTH marks are frozen SPY-proxy quotes, and paper position IDs can overwrite open positions across days.
2. **Strategy coherence (prune + exit timing) — WARN.** Pruning identical-book clones was correct. Pruning the 45–60 DTE OTM operator stagger as "0 entries / starved" after ~3 trading sessions (added `e6bb155` 2026-07-09, pruned 2026-07-13) is **not evidence** — and `conductor_shadow` hard-blocks any entry the day after SPY falls >1.5% (`conductor_shadow.py:33-37`), which structurally suppresses the very dip-bounce entries the operator thesis needs. `cc12ad5`'s "exit whenever session open" is coherent in code but **unmeasurable in paper** overnight (SPY proxy has no GTH quotes).
3. **Live RH flip readiness (David's account) — FAIL.** Kill switch, review→place grant, quantity caps, debit gates, exact allowlist, and deterministic reviewer are genuinely solid. But: live-exit fan-out from variant monitors is still open (v8 P0 #3), the live `cheapest_near_atm` selector does **not** match the paper selector, the pinned-account gate degrades to a no-op if both pin and order account are empty, there is no pin-vs-token cross-validation, the monitor cannot even import on David's Windows box (`import fcntl`), and the OAuth token path defaults to a OneDrive-synced folder.
4. **Any variant promotable this week — NO (FAIL).** Promotion requires `edge_confirmed` (≥20 sessions, ≥20 trades, avg>0, Wilson-LB > breakeven). The scoreboard is missing from the pack, so nothing can be certified; even optimistically, dip-swing trades hold for days — 20 closed trades per variant is a multi-week horizon at best.

---

## Phase A — Accuracy & measurement integrity

### A1. v7/v8 P0 regression check at HEAD

| v8 P0 | Status at `cc12ad5` | Evidence |
|---|---|---|
| Paper exits under MCP-on (v8 #0) | ✅ fixed for the common case, ⚠️ **regression window remains** | `lane_a_monitor.py:1170-1184` loads/refreshes paper positions regardless of RH read path; `paper_positions_active = bool(state.get("paper_positions")) and not positions_override` (`:1253`). **But** `lane_a_monitor.py:1206` — `if not classified and state.get("paper_positions")…` — only feeds the paper book into exit evaluation when RH returned **zero** classified positions. The moment a real XSP call exists on David's account, `classified` is the RH position, paper positions get marks refreshed but **never generate alerts**, so `close_paper_positions_on_exit` (keyed on alert IDs, `:794`) closes nothing. Mixed live+paper operation re-freezes the paper/shadow books — exactly the failure v8 called #1. |
| `max_debit_usd` full-debit gate | ✅ | `lane_a_entry.py:1268-1280`; config `lane_a_rules.yaml` `live.max_debit_usd: 2500`, `documented_min_buying_power_usd: 5000`, `max_cost_frac: 0.5` |
| Exact live allowlist | ✅ | `lane_a_entry.py:1147-1153` — exact string equality, empty fails closed; no `endswith` |
| Mark guards (+90 / −80 / jump) | ✅ | `spy_quote.py:135-157` (`ret > 0.90`, `ret < -0.80`, `mark_jump > 0.22` clamp) |
| SL fires on stale mark, TP suppressed | ✅ | `lane_a_monitor.py:567` `allow_take_profit = not pos.mark_quote_stale`; stop-loss branch has no staleness gate (`:569`) |
| VIX-spike falling-knife veto | ✅ | `lane_a_entry.py:913-926` + `lane_a_rules.yaml` `vol_shadow.veto_entry_on_vix_spike: true` |
| Reviewer aligned (`max_contracts` 2) | ✅ | `lane_a_rules.yaml` `reviewer_max_contracts: 2` = `rh_mcp.yaml` `max_contracts_per_order: 2` |

### A2. Scoreboard / paper-dollar trust

- `premium_scale: 10.0` dual-logging is correctly implemented: `build_scoreboard` emits `realized_pnl_usd_1x_approx` / `avg_pnl_per_trade_usd_1x_approx` per variant (`lane_a_variants.py:1351-1358, 1391-1392`) and the brief carries `open_positions_mtm_usd_1x` (`lane_a_monitor.py:1096-1100`). Guidance text forbids summing across variants (`lane_a_variants.py:1508-1511`).
- ⚠️ **Exception:** `_build_contract_clusters` **does sum `realized_pnl_usd` across variants** within a contract cluster (`lane_a_variants.py:1033-1037`). It's labeled diagnostics, but it is exactly the cross-variant sum the audit rules forbid, and it will read as a headline number to a skimmer. Tag it `not_additive` or drop the sum.
- 🔴 **The pack itself is the biggest measurement failure this round.** All 20+ runtime artifacts are placeholders: `variants_scoreboard.json` → `(missing: …briefs/xsp-lane-a-variants-scoreboard.json)`, same for `variants_state.json`, `lane_a_paper_pnl_latest.json`, `entry_telemetry_latest.json`, `paper_log_lane_a.jsonl`, `health_soak_latest.md`, both variant log tails; `deployment_status.txt` → `[WinError 2]`; `pytest_results.txt` → `python3` exit 1. The pack builder ran on the Windows clone where the soak has never run. **No auditor in this council can verify a single realized-PnL, session-count, or promotion-gate claim.** Any GO decision that cites soak numbers this round is citing nothing.

### A3. New measurement breaks from `43fdda8` / `cc12ad5`

- `evaluate_exit_alerts` now gates only on `xsp_session_open` (`lane_a_monitor.py:556`) — the legacy sell/no-sell clock fields are correctly inert (`00:00–23:59` / `00:00–00:00`, and `evaluate_exit_alerts` never calls `in_sell_window`). Consistent.
- 🔴 **Paper cannot see the premarket window it now claims to trade.** The monitor timer fires every 15 min around the clock Mon–Fri (`deploy/systemd/xsp-killer-lane-a-monitor.timer`), and exits are eligible during GTH — but paper marks come from the **SPY option chain via yfinance** (`refresh_paper_marks` → `fetch_spy_call_quote`), which is frozen at the prior RTH close overnight. There is no market-hours staleness check in `spy_quote.py` (guards are magnitude-based only). Consequences: (a) any GTH "exit" the paper book logs between 20:15 and 09:25 is filled at **yesterday's close mark** while being timestamped premarket — a fictional fill; (b) the actual alpha claim of `43fdda8` ("sell into the 08:00–09:30 spike") is **unmeasurable in paper** and will only ever be observed live. The paper soak therefore cannot validate the exit-timing change it is supposed to be soaking.
- ⚠️ `_position_return_pct` uses `entry_mid_premium` (mid) while the fill was `average_price` (mid+slippage+commission) — intentional and consistent, fine.
- ⚠️ **Paper position-ID collision:** `pos_id = f"paper:{chain}:{exp}:{int(strike)}"` (`lane_a_entry.py:391`) and unconditional insert (`:1068-1069`). Dip-swing variants allow `max_open_positions: 3` across days; two entries on consecutive days picking the same expiry+strike (likely when SPX is flat) **silently overwrite the first open position**, destroying its record and mis-stating open-position count and eventual realized PnL. Include `entry_ts`/date in the ID.

---

## Phase B — Strategy & logic

### B1. Was pruning far-DTE OTM (45–60) correct?

**Premature.** The four operator-target variants existed for **~3 trading sessions** (Jul 9 → Jul 13 prune, spanning a weekend) before being marked `pruned 2026-07-13: 0 entries / starved`. Three structural observations:

1. Their entry signal is **identical** to the still-active 14/21-DTE dip-swing variants (same `DIP_BOUNCE` gate, same VWAP-reclaim bounce). If 14-DTE entered in that window and 45–60 didn't, that indicates a selection bug (e.g., `pick_expiration` target resolution on the SPY chain), not absence of thesis — and if *nobody* entered, "starved" is just "no dip happened in 3 days."
2. `conductor_shadow.shadow_review_entry` **blocks all entries the day after SPY falls >1.5%** and on regime RED (`conductor_shadow.py:30-37`) — despite the "shadow" name it actually vetoes (`lane_a_entry.py:1077-1088` pops the position). Real dips big enough to trigger a BB-bounce entry disproportionately follow >1.5% down days. This filter is directly adversarial to the dip-buy thesis and is the most plausible systemic starvation mechanism for the whole cluster. It defaults **on** (`XSP_LANE_A_CONDUCTOR_SHADOW=true`).
3. The starvation evidence (entry telemetry, variant logs) is **missing from the pack**, so the prune cannot be validated. Verdict: keep the prune operationally (capacity), but treat 45–60 OTM as *untested*, not refuted — and re-run it only after the conductor_shadow interaction is measured.

### B2. Premarket sell window + session-open exits — +EV?

Directionally sensible for a swing book (capture overnight gap-ups; morning 08:00–09:30 is historically where overnight gains concentrate). Two live risks: (a) **XSP GTH liquidity is thin** — spreads blow out overnight, and the exit order is a **limit at mark** (`_build_close_order`, `lane_a_monitor.py:899-919`); a mark-based limit into a thin premarket book will frequently not fill or fill badly. (b) In paper it is unmeasurable (A3), so the +EV claim will remain an assumption until live. Recommend: for GTH exits, require a live bid/ask from MCP and price the limit off the bid, not the mark.

### B3. Active 12-keeper grid

Confirmed 12 active in `config/lane_a_variants.yaml`: `v2_14dte_atm`, `v2_28dte_atm`, `v2_28dte_atm_stack3`, `v2_28dte_easy_tp`, `v2_28dte_green_day`, `v2_yellow_mid_bounce`, plus 6 dip-swing (`14dte`, `21dte`, `14dte_tp25`, `14dte_tp60`, `21dte_otm`, `14dte_spread`). Clone pruning (identical realized books) was the right call. Remaining confounding: `v2_28dte_atm` vs `v2_28dte_atm_stack3` differ only in stacking and will produce near-identical books until multiple signals stack; `v2_dip_swing_14dte` vs `_spread` differ only in a log-only shadow — expect another identical-book pair. Effective information content is ~9 distinct experiments. Promotion math (`PROMOTION_TRADES_GATE=20`, Wilson-LB > breakeven, `lane_a_variants.py:1362-1375`) is statistically honest; at swing-hold turnover (≤3 concurrent, multi-day holds) 20 closed trades is realistically **8–12+ weeks** per variant.

### B4. Operator ~55 DTE OTM 2-lot vs live keepers — what should David promote first?

Neither this week. When a first live promotion happens, promote the **shortest-runway edge-confirmed dip-swing keeper (14 or 21 DTE ATM)** rather than the 55-DTE OTM aspirational: (a) it will have real closed-trade evidence first; (b) at ~$2–4 XSP premium a 1–2 lot fits the $1k–5k account with the `max_debit_usd`/`max_cost_frac` gates binding sanely; (c) the 55-DTE OTM 2-lot (~$2.4k debit) consumes nearly the whole `max_debit_usd: 2500` cap and half of the documented $5k BP floor on trade one, with vega-crush on recovery unmodeled (v8 consensus, still true). The operator profile stays a reference until the far-DTE grid is re-soaked with the conductor_shadow interaction understood.

---

## Phase C — Bugs & edge cases

1. **Race / double-exit / partial fill under review→place.** The in-memory grant (`_active_grant`, `robinhood_mcp.py:502-510`) is per-adapter-instance and cleared on place — cron runs are single-shot, so grant replay across processes is impossible (good, fail-closed). Deterministic `ref_id` per (option, day, reason) (`lane_a_monitor.py:892-896`) dedupes across the 15-min runs. **Two holes:** (a) if `place_option_order`'s HTTP call times out after the server accepted, the client records an error but the order may live — retry is safe only because of `ref_id`; entries share the same protection (`_live_entry_ref_id`). OK. (b) 🔴 **No reprice path:** a GFD sell **limit at mark** that doesn't fill (gap through the stop, thin GTH) can never be re-placed that day — same (option, day, `stop_loss`) → same `ref_id` → broker dedupe swallows every subsequent attempt, and there is no cancel-and-replace logic anywhere. A live stop-loss can silently fail for an entire session. Partial fills: remaining quantity is only re-attempted next day (new date → new ref_id), using the then-current position quantity — acceptable, but same-day remainder is unprotected.
2. **Live exit fan-out (v8 P0 #3) — still open.** `cf79281` only suppressed the **canary** on variant monitors (`lane_a_monitor.py:1244-1251`: skip only when `not all_alerts and not _has_rh_positions`). When a real RH position exists and **any variant's rules** fire an alert (e.g., `easy_tp` at +10% while baseline waits for +20%+BB), that variant monitor calls `dry_run_exit_reviews_via_mcp` → with `LIVE_EXITS=true` it **places** under the variant's rules. Different variants also produce different `exit_reason`s → different `ref_id`s → the broker's idempotency cannot dedupe a `take_profit` from one variant against a `stop_loss` from another. There is no exit-side `XSP_LANE_A_LIVE_VARIANT_ID`. Must be fixed before the LIVE_EXITS flip.
3. **Account pin empty → fail-closed?** Mostly yes: `_live_flag` (`robinhood_mcp.py:215-227`) returns False without a pinned account, so both open and close placements are refused (I7). **But** the I3 account check itself is vacuous when pin or order-account is empty: `if pinned and account and account != pinned` (`robinhood_mcp.py:602`). Today that's shielded by I7's pin requirement, *but only because* `RhMcpConfig.load()` happens to read `RH_AGENTIC_ACCOUNT_ID` (`:193`). An adapter constructed with an explicit config object that lacks the pin while the env var is set passes I7 (env) yet skips both I3 and `_inject_account` → an order with **no account_number** goes to the server's default account. Defense-in-depth: `place_option_order` should hard-require a non-empty pinned account and stamp it, unconditionally.
4. **Clock/session helpers vs `evaluate_exit_alerts` after `cc12ad5` — consistent.** `in_sell_window`/`in_no_sell_window` survive only for shadow-bracket compatibility and are not consulted by `evaluate_exit_alerts` (`lane_a_monitor.py:537-627`). `xsp_session_open` correctly models GTH/RTH/curb including the 09:25–09:30 dead zone and weekends. Config legacy fields are inert values.
5. **Paper vs live selector parity — BROKEN for the default mode.** 🔴 Paper `cheapest_near_atm` = *nearest-to-ATM first, cheapest only as tie-break* (`lane_a_entry.py:311-319`: `if dist < best_dist or (dist == best_dist and … cheaper)`). Live `cheapest_near_atm` = *globally cheapest ask in the ±1 window* (`robinhood_mcp.py:948-949`: `min(enriched, key=lambda c: c["ask"])`), which for calls systematically selects the **highest (OTM) strike**. The baseline and `v2_14dte_atm`-style variants would soak ATM-ish paper trades while live buys 1-step OTM — different delta, different theta, invalidating the soak→live transfer. v8 marked "live selector ≠ paper" CLOSED for `dte_target`/`otm_one`; `cheapest_near_atm` was missed. Also: live `select_entry_contract` ignores `exclude_expiry_month` (`robinhood_mcp.py:887-909`), so a December live entry could take a January expiry that paper excludes (P2). DTE parity is approximate (XSP dailies vs SPY-chain proxy expirations). Quantity parity is fine (`qty = max(1, round(entry_rules.quantity))`, capped at 2 twice).

Additional: `kill_switch_engaged` returns **False on OSError** reading the kill file (`robinhood_mcp.py:139-142`) — the emergency stop fails *open* on I/O error; invert it. `RhMcpLiveExitsDisabled`'s docstring says "kill switch" (cosmetic). `_live_flag` accepts `on` for the kill switch but not for live flags (harmless asymmetry, biased safe). K155–K162 spikes: verified log-only — monitor attaches `macro_weather_extras` inside a try/except with no gate coupling (`lane_a_monitor.py:1153-1163`); muse/fable spike modules are not imported by entry/monitor paths. No entry/exit influence found.

---

## Phase D — RH Agentic order placement (David's setup readiness)

### D1. What David must do before first read / first write

**Before first read:** (1) Desktop OAuth to `https://agent.robinhood.com/mcp/trading` (Cursor → Tools & MCPs, or the Claude-CLI tunnel flow in `docs/rh_mcp_runbook.md:32-67`); (2) export the token JSON (`access_token` key) to `.local/robinhood_mcp_token.json` — **but see D6/E2: on David's machine that path is inside OneDrive**; (3) set `XSP_LANE_A_RH_MCP=true`; (4) run `scripts/rh_mcp_health.py` (works on Windows — it avoids the `fcntl` modules) and confirm positions read + confidence tier HIGH. **Before first write:** (5) run `get_accounts`, identify the **Agentic** account number, set `RH_AGENTIC_ACCOUNT_ID` (env) or `agentic_account_id` (config — currently `""`); (6) fund the Agentic account ≥ `documented_min_buying_power_usd` context ($5k for the 2-lot profile, $1k minimum for 1-lot); (7) only then flip `XSP_LANE_A_LIVE_EXITS` / `_ENTRIES` per phase. **Missing step the runbook should add:** verify the pinned account number appears in `get_accounts` *under David's token* — nothing in code or health check cross-validates pin vs token identity today.

### D2. Order path failure modes, kill switches, quantity caps

`review_option_order` → in-memory grant keyed on canonicalized order (account, type, qty, price, legs; `_review_grant_key`, `robinhood_mcp.py:339-353`) → `place_option_order` requires matching grant (I2), kill switch clear (I8), live flag + pin (I7), `max_contracts_per_order` with leg-ratio multiplication (I5, `:578-594`), account pin match (I3). Deny paths audit to `logs/rh_mcp_audit.jsonl` with invariant tags. Entry path adds: buying power, `max_loss_usd` (1200), `max_debit_usd` (2500), `max_cost_frac` (0.5), RED-regime veto, VIX-spike veto, exact variant allowlist, and the deterministic fail-closed reviewer (`conductor_reviewer.py` — genuinely fail-closed, vetoes on any missing field). Kill switches: env flag, sentinel file, per-direction live flags, RH-app agent disconnect, systemd stop — a good ladder. **Weaknesses:** no grant TTL (a review from hours earlier in a long-lived process still authorizes), K37 `shadow_review_order` runs *before* the write gates but is verified fail-open (`k37_reviewer_shadow.py:28-47`), no reprice/cancel-replace for unfilled exits (C1), kill-file check fails open on OSError.

### D3. Can writes hit a non-Agentic / Claudio account?

- **Claudio's account:** only if David's box uses **Claudio's token file** (e.g., copied from cemini-prod during setup). The token, not the config, decides whose brokerage the MCP server acts on. With David's pin set but Claudio's token, the server should reject the mismatched account number — but the adapter never checks, and if the pin were *also* copied from cemini-prod docs, orders would route to Claudio cleanly. **Mitigation required:** health-check assertion `pinned ∈ get_accounts(token)` + a `token_subject` log line at startup (the field exists in `_session_principal` but is never validated).
- **David's non-Agentic account:** `resolve_account_number()`'s single-account / nickname fallback (`robinhood_mcp.py:645-673`) affects **reads only**; the write path injects only the configured pin. Residual risk is the C3 empty-pin construction hole and the operator pinning the wrong account number. Code-level: adequately closed **provided the pin is set and validated**.

### D4. Fail-closed matrix (LIVE_ENTRIES / LIVE_EXITS / LIVE_VARIANT_ID)

| State | Result |
|---|---|
| MCP off | No network at all (`rh_mcp_enabled` gate in every path) — closed |
| MCP on, no token | `RhMcpNotReady`, reads return `([], error)` — closed |
| MCP on, no pin | Both live flags force-false (`_live_flag`) — closed |
| Flags on + pin, kill switch | All placement blocked, cancels allowed (I8) — closed |
| ENTRIES on, VARIANT_ID unset/mismatch | Entry skipped, "variant not in live allowlist" — closed |
| EXITS on | ⚠️ **No exit-side variant allowlist** — every variant monitor with an alert places (C2). This is the hole. |
| `.env` on VPS | ⚠️ `EnvironmentFile=-/opt/xsp-killer/.env` loads **after** the unit's `Environment=` lines and overrides them — a stray `XSP_LANE_A_LIVE_EXITS=true` in `.env` silently defeats the unit-file `false`. Grep `.env` before every flip. |

Ambiguous/missing `position_effect` defaults to **exit** semantics (`:561`) — the stricter-for-opens choice, correct. Verdict: entries fail closed convincingly; **exits have the fan-out hole**; nothing found that places on David's RH with all flags at documented defaults.

### D5. Options tool rollout / stale-quote risk

Tool allowlist is frozen (`READ_TOOLS`/`WRITE_TOOLS`); non-allowlisted tools deny with I5 audit. Schema drift is partially absorbed by `normalize_mcp_position` and the confidence classifier (`data_hazards.py:98-116`) — LOW-tier reads are refused for monitor decisions with an I6 deny row (`robinhood_mcp.py:1078-1096`), which is real fail-closed plumbing. Entry: no ask → contract skipped → `RhMcpError` → no place (`select_entry_contract:930-947`). Exit: **no mark → market order** (`_build_close_order:917-918`) — for risk exits that's defensible but on thin GTH it's a blank check; consider bid-referenced limits or RTH-only market orders. Empty positions read scores 0.65 (MEDIUM, trusted): a transient empty read isn't treated as "positions vanished" — no auto-action results, safe.

### D6. Ranked GO/NO-GO

1. **Paper-only soak: GO** — with the A3/A1 measurement caveats fixed or accepted, and the pack rebuilt from the VPS.
2. **MCP reads on David's account: GO after** OAuth + pin + health check + moving the token out of OneDrive (E2). Reads are well-gated and confidence-wrapped.
3. **Live exits only: NO-GO** until (a) exit fan-out variant gating ships, (b) pin-vs-token validation exists, (c) an unfilled-stop reprice/cancel policy exists, (d) `.env` override audited.
4. **Live entries: NO-GO** — no `edge_confirmed` variant (unverifiable regardless from this pack), plus the C5 `cheapest_near_atm` parity bug means the soak evidence wouldn't even describe the contract live would buy.

---

## Phase E — Ops / foreseeable issues

1. **Windows vs Linux:** `lane_a_monitor.py:9` and `lane_a_variants.py:5` `import fcntl` — **the monitor/variant stack cannot import on David's Windows workspace at all.** The runbook, k37 (`/opt/cemini` sys.path), and systemd assume the VPS. Decide explicitly: David's *token* on the **VPS** deployment (recommended — one supervised runtime), or port the locking (`portalocker`/`msvcrt`) before any local-Windows live plan. The operator-context line "local Windows workspace" is currently incompatible with the code.
2. **OneDrive sync risk — real:** repo root is `C:\Users\Owner\OneDrive\Desktop\xsp-killer`; `token_path` and the kill-switch sentinel default to `ROOT/.local/…` (`robinhood_mcp.py:172-174, 136-138`). On David's machine the **OAuth bearer token would sync to Microsoft's cloud**, and the kill file becomes subject to OneDrive file-on-demand/sync races (the `OSError → False` fail-open makes that worse). If anything runs locally, set `token_path` and `XSP_LANE_A_KILL_FILE` to a non-synced location (`%LOCALAPPDATA%`), and note `.local/` mode-600 advice does nothing on NTFS.
3. **Timer load / observability:** monitor timer fires 96×/day including overnight GTH no-op…-ish runs that still hit yfinance and (baseline) run a canary review when MCP is on; 12 variants ≈ 30s at 15:45 is fine per config header. Gaps: monitor `errors[]` land only in a JSON brief nobody pages on; repeated MCP token-expiry failures with an **open live position** would silently disable stop-loss protection (D2/C1) — add an alert on `rh_connected=false` streaks and on `rh_mcp_audit.jsonl` deny bursts. `env_example.txt` omits `XSP_LANE_A_LIVE_ENTRIES`, `XSP_LANE_A_LIVE_VARIANT_ID`, `XSP_LANE_A_KILL_SWITCH` — document them.
4. Ranked backlog: below.

---

## Cross-auditor disagreement hooks

1. **Was the 45–60 DTE OTM prune "starvation" real signal absence, a `pick_expiration` bug, or `conductor_shadow`'s >-1.5% prior-day block suppressing dip entries cluster-wide?** I claim it's unadjudicable from this pack (logs missing) and ≤3 sessions is not evidence; other auditors citing "0 entries" as thesis-refutation are over-reading.
2. **`cheapest_near_atm` paper/live divergence (C5).** v8 marked selector parity CLOSED; I claim the default mode is still divergent (nearest-ATM vs min-ask). If another auditor reads `min(enriched, key=ask)` as equivalent, cross-check with a 3-strike example.
3. **Is the `lane_a_monitor.py:1206` mixed-book starvation a live blocker or a papercut?** I rank it P1 (it re-opens v8 P0 #0 the day the first live entry fills); an auditor assuming paper and live books never coexist may rank it P3.

---

## Ranked patch backlog

### P0 (before any live flag flips; #3 before trusting this audit round)
1. **Exit-side variant gating:** restrict `place_option_order` on exits to the baseline/promoted monitor (exit-side `XSP_LANE_A_LIVE_VARIANT_ID` or skip placement entirely on `_variant_monitor` passes) — `lane_a_monitor.py:1244-1251`, `dry_run_exit_reviews_via_mcp`.
2. **Selector parity:** make live `cheapest_near_atm` replicate paper's nearest-ATM-then-cheapest ordering (or rename/re-soak) — `robinhood_mcp.py:948-949` vs `lane_a_entry.py:311-319`.
3. **Rebuild the v9 pack on the VPS** (all runtime artifacts missing; pytest never ran) and re-issue soak-dependent verdicts.

### P1 (before David's RH bring-up)
4. Mixed-book paper-exit starvation when real RH positions exist — `lane_a_monitor.py:1206` (evaluate paper book unconditionally).
5. Hard-require non-empty pinned account at place time + health-check `pin ∈ get_accounts(token)` — `robinhood_mcp.py:601-607, 645-673`.
6. Unfilled live stop-loss: cancel-and-replace or ref_id versioning per retry window — `lane_a_monitor.py:892-919`.
7. Paper position-ID collision across days — `lane_a_entry.py:391, 1068`.
8. Move token + kill file out of OneDrive; kill-file check fail-closed on OSError — `robinhood_mcp.py:136-142`.
9. Decide VPS-vs-Windows runtime; `fcntl` blocks local Windows — `lane_a_monitor.py:9`.
10. GTH paper marks: tag SPY-proxy quotes stale outside RTH so overnight paper exits can't book fictional premarket fills — `spy_quote.py`.
11. Measure/disable `conductor_shadow`'s prior-day −1.5% block for `DIP_BOUNCE` variants before re-judging the dip thesis — `conductor_shadow.py:33-37`.

### P2
12. `contract_clusters` cross-variant PnL sum labeling (`lane_a_variants.py:1033-1037`); grant TTL; `exclude_expiry_month` in live selector; `.env`-overrides-unit-file audit note in runbook; `env_example.txt` missing live/kill vars; `RhMcpLiveExitsDisabled` docstring; GTH exits should price off bid not mark.

---

**Summary (executive verdicts + top findings):**

1. Verdicts — Paper soak/measurement: **WARN**; Strategy coherence: **WARN**; Live flip readiness (David): **FAIL**; Promotable this week: **NO**.
2. **P0-A:** v9 pack has **zero runtime evidence** — every soak artifact is `(missing:…)`, pytest never ran (Windows pack build); no soak claim this round is verifiable. Rebuild pack on the VPS.
3. **P0-B:** Live-exit fan-out (v8 P0 #3) still open — variant monitors place exits on the shared real position under variant rules; different `exit_reason`s defeat ref_id dedupe (`lane_a_monitor.py:1244-1251`).
4. **P0-C:** Paper/live selector divergence: live `cheapest_near_atm` = min-ask → systematically buys 1-step OTM; paper = nearest-ATM (`robinhood_mcp.py:948-949` vs `lane_a_entry.py:311-319`) — soak evidence wouldn't describe the live contract.
5. **P1:** Paper exits starve again once a real RH position exists (`lane_a_monitor.py:1206`, `if not classified…`) — v8 P0 #0 regression under mixed live+paper.
6. **P1:** Unfilled live stop-loss can't be re-placed same day (ref_id per option/day/reason, no cancel-and-replace — `lane_a_monitor.py:892-919`); position unprotected all session after a gap.
7. Also load-bearing for David: `import fcntl` blocks the whole monitor stack on Windows (`lane_a_monitor.py:9`); OAuth token + kill file default **inside OneDrive** (`robinhood_mcp.py:136-142, 172-174`); no pin-vs-token validation anywhere.
8. Strategy: 45–60 DTE prune after ~3 sessions is not evidence; `conductor_shadow` blocks entries after >1.5% down days — structurally anti-dip-thesis (`conductor_shadow.py:33-37`).
9. Genuinely solid: kill-switch ladder, review→place grants, exact allowlist, `max_debit_usd`/reviewer gates, LOW-confidence read refusal — entries fail closed convincingly.
10. Note: I'm in Ask (read-only) mode, so `fable-5_AUDIT.md` was **not** written to disk — the full report above is ready to save verbatim to `reports/gap-audit/premium-xsp-killer-v9-cursor/fable-5_AUDIT.md`.

I'm spotting a critical issue with the shadow_review_entry logic — it's blocking entries when SPY drops more than 1.5% the prior day or when the regime is RED, but for dip-bounce strategies this is backwards since they're designed to buy confirmed bounces after down days. This blocking mechanism might be the root cause of the zero-entry problem starving the strategy.

The conductor_shadow block applies uniformly across all variants in the entry logic, yet I'm noticing something odd: the 14-DTE and 21-DTE dip variants did get entries despite identical entry gates, while the 45-60 DTE variants show zero entries. The DTE cutoff shouldn't affect the far-DTE variants differently, so the issue might be in how expiration candidates are selected — the pick_expiration logic targets 45-60 day monthlies, but something in the contract filtering or lane selection could be excluding them.

I'm also realizing the "starved" label is misleading since it only spans 2-3 sessions with a weekend gap, and I don't even have confirmation that dip signals occurred during those sessions. The missing entry telemetry makes it impossible to verify whether conductor_shadow actually blocked entries or if there simply weren't any dip triggers to begin with. This is a solid disagreement point to flag.

Now I'm ready to write the full markdown audit report with the required structure and format, then provide the 8-12 line summary at the end.

Compiling the verdicts: measurement integrity is WARN due to unverifiable soak numbers and mixed starvation signals, strategy coherence is WARN because the far-DTE prune was premature and conductor_shadow contradicts the dip thesis, live RH flip readiness is FAIL across multiple validation gaps, and promotability this week is also FAIL.