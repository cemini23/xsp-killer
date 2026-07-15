# XSP Killer SUPER AUDIT v9 — Auditor 3/6 (kimi-k2.7-code) Strategy + Ops Lens

**Model slot:** `kimi-k2.7`  
**Pack:** `reports/gap-audit/pack-xsp-killer-v9`  
**Repo:** `C:\Users\Owner\OneDrive\Desktop\xsp-killer`  
**HEAD audited:** `cc12ad5` ("fix(lane-a): exit on conditions whenever XSP session is open")  
**Date:** 2026-07-15  
**Audit lens:** strategy after prune, promotion readiness, David's local RH bring-up, Windows/OneDrive/token ops, contradictory docs vs code.

---

## Executive Verdict

| Question | Verdict | Why |
|---|---|---|
| **Paper soak trustworthy?** | **FAIL / HOLD** | `pytest_results.txt` reports non-zero exit at HEAD; briefs/scoreboard artifacts are missing from repo; the 12-keeper grid is mostly dip-swing clones with thin sample. |
| **Variant promotion ready this week?** | **NO — WAIT** | No active variant is near the ≥20-session / ≥20-trade gate; scoreboard is absent; operator 55 DTE aspirational is pruned inactive. |
| **David RH setup ready for reads?** | **CONDITIONAL NO-GO** | Token path is empty, `.local/` lives under OneDrive, systemd/Linux paths are hardcoded, Windows `fcntl` will fail. |
| **David RH setup ready for live exits?** | **NO-GO** | `LIVE_EXITS=false` is correct, but the variant monitor fan-out risk and Windows path issues must be fixed first. |
| **David RH setup ready for live entries?** | **NO-GO** | `LIVE_ENTRIES=false`, `agentic_account_id` empty, no Task Scheduler automation, and tests are failing. |
| **Contradictions under control?** | **NO — P1** | Runbook targets `/opt/xsp-killer` (cemini-prod), not David's Windows workspace; docs are stale vs HEAD. |

**Overall:** this is a **paper-only, fix-first** posture. Do not flip any live flag on David's RH until (1) tests pass, (2) Windows automation is wired, (3) token storage is moved out of OneDrive, and (4) the variant-monitor exit fan-out is gated.

---

## Phase A — Accuracy & Measurement Integrity

### 1.1 v7/v8 P0 fixes at HEAD

| P0 | Status | Evidence |
|---|---|---|
| Paper exits under MCP | ✅ structurally fixed | `lane_a_monitor.py:1206-1267` now evaluates paper positions even when `rh_read_enabled()` is true; `close_paper_positions_on_exit` closes on first alert. |
| Exact live allowlist | ✅ fixed | `lane_a_entry.py:1147-1153` `_live_variant_allowed` uses exact string equality. |
| `max_debit_usd` gate | ✅ present | `lane_a_entry.py:1268-1279` rejects orders when `cost > max_debit_usd`. |
| VIX spike veto | ✅ present | `lane_a_entry.py:911-926` calls `vix_spike_entry_veto`; `vol_monitor.py` defaults to shadow-only unless `veto_entry_on_vix_spike` is true. |
| SL on stale mark | ✅ fixed | `lane_a_monitor.py:566-567` suppresses take-profit on `mark_quote_stale` but still fires stop-loss. |

### 1.2 New measurement breaks from `43fdda8` + `cc12ad5`

The two most recent commits changed the exit semantics:

- `43fdda8`: sell into the 08:00–09:30 premarket spike window.
- `cc12ad5`: remove clock sell/no-sell gate; evaluate exits whenever XSP session is open.

`lane_a_monitor.py:537-628` now has no `time_stop` unless `swing_hold=true` and `dte <= max_hold_dte`. This is correct for the new thesis, but the legacy `sell_eval_start_et`, `sell_deadline_et`, `no_sell_start_et`, `no_sell_end_et` fields still exist in `LaneRules` and `lane_a_rules.yaml` — they are ignored by `evaluate_exit_alerts` but still parsed. This is a documentation/legacy-contradiction risk: a future operator could think the morning clock window still matters.

`lane_a_rules.yaml:279-288` explicitly says "Exit anytime XSP is tradeable... Legacy window fields kept for shadow bracket compatibility only; evaluate_exit_alerts ignores them." That is honest, but the YAML still carries `sell_deadline_et: 09:30` and `no_sell_end_et: 08:00`, which is confusing when the code no longer enforces them.

### 1.3 Scoreboard / paper $ trust

- `paper_economics.py:15-20` dual-logs scale via `premium_scale` (10× default) and `*_1x_approx` in the scoreboard.
- `lane_a_variants.py:1351-1358` computes `realized_1x` and `avg_pnl_1x` by dividing by scale.
- However, the comparison guidance is only in code; the scoreboard JSON is **missing from the repo** (`briefs/xsp-lane-a-variants-scoreboard.json` not found), so we cannot verify the current epoch or sample size.
- `pytest_results.txt` reports the whole test suite failed with exit status 1. A failing test suite at HEAD makes the entire measurement pipeline untrustworthy until the failures are diagnosed and fixed.

---

## Phase B — Strategy & Logic

### 2.1 Was pruning far-DTE OTM correct?

**Verdict: probably correct, but it creates a tension with the operator thesis.**

`lane_a_variants.yaml:441-547` shows the four operator target variants (`v2_dip_swing_45/50/55/60dte_otm`) are all `active: false` with comments "pruned 2026-07-13: 0 entries / starved (far-DTE OTM)". The audit prompt confirms this was intentional.

The problem is not the prune itself — it is that the operator aspirational profile (55 DTE OTM, 2-lot) is no longer generating any sample. That means:
- We cannot validate whether the operator thesis is +EV.
- The active grid (`v2_14/21dte` dip-swing and yellow-bounce variants) is a different strategy: short-dated, near-ATM, intra-day BB-bounce entries with 40–60% TP and 50–60% SL.

If David promotes the active keepers, he is not promoting the operator 55 DTE profile; he is promoting a short-dated dip-swing profile. That is a material strategy drift.

### 2.2 DTE collision in the pruned operator stagger

`tests/test_operator_dte_stagger.py:46-51` documents that with the SPY Friday calendar used in the test, 55 and 60 DTE targets both resolve to `2026-09-03`. The test asserts this as "documented soak risk." Even if re-enabled, the 45–60 bucket cannot be cleanly separated because XSP/SPY expirations are weekly but the target buckets fall on the same Friday when the next Friday is outside `dte_max=60`.

This means the operator stagger was never statistically well-posed. Collapsing it to a single far-DTE bucket (or keeping it inactive) is the right call.

### 2.3 Active 12-keeper grid: clones and promotion path

Active variants per `tests/test_lane_a_variants.py:32-45` and `lane_a_variants.yaml`:

1. `v2_14dte_atm`
2. `v2_28dte_atm`
3. `v2_28dte_atm_stack3`
4. `v2_28dte_easy_tp`
5. `v2_28dte_green_day`
6. `v2_yellow_mid_bounce`
7. `v2_dip_swing_14dte`
8. `v2_dip_swing_21dte`
9. `v2_dip_swing_14dte_tp25`
10. `v2_dip_swing_14dte_tp60`
11. `v2_dip_swing_21dte_otm`
12. `v2_dip_swing_14dte_spread`

**Issues:**
- Several are intentionally clones/duplicates that were pruned (`v2_28dte_cheapest`, `v2_28dte_wide_sl`, `v2_yellow_top_quartile_bounce`, `v2_dip_swing_14dte_loose`, `v2_dip_swing_30dte`) because they produced identical realized books.
- The remaining active grid is still dominated by the dip-swing family. That is fine for exploration, but it means the "12 keepers" are not 12 independent hypotheses.
- `v2_dip_swing_14dte_spread` is a debit-spread shadow prototype; it still trades the naked long call and only logs spread economics. This is experimental and should not be promoted first.

**Promotion math:** `lane_a_variants.py:56-58` requires `PROMOTION_SESSIONS_GATE=20`, `PROMOTION_ENTERED_SESSIONS_GATE=10`, `PROMOTION_TRADES_GATE=20`. With the scoreboard missing, no variant can be shown to have cleared these gates. **Promotion is not possible this week.**

### 2.4 Premarket spike window + session-open exit

`43fdda8` added selling into the 08:00–09:30 premarket window. `cc12ad5` then removed any clock gating. The net effect is that the system can exit in GTH (20:15–09:25), RTH (09:30–16:15), or curb (16:15–17:00).

**Risk:** XSP liquidity in GTH is materially thinner than RTH. The code uses a limit order at mark when placing live exits (`lane_a_monitor.py:899-919`), but the mark itself comes from RH MCP `get_option_quotes`. In thin GTH markets, the mark can be stale or wide, and a limit-at-mark sell may not fill promptly. This is a +EV question that cannot be answered from code; it requires live market data.

**Contradiction:** `lane_a_rules.yaml:265-288` still carries the legacy window/no-sell fields, and `docs/lane-a-brief.md` / `strategy_diagnosis.md` (2026-06-29) predate the dip-swing pivot. Operators reading those docs will expect a 09:30–10:00 morning exit window, not a 24-hour session-open model.

### 2.5 Which variant should David promote first?

Given the active grid and the live safety constraints, the safest first live candidate would be a **single-contract, near-ATM, short-dTE baseline** (e.g., `v2_28dte_atm` or `v2_14dte_atm`) rather than any 2-lot operator profile. The live gate in `lane_a_rules.yaml:356-369` already caps at `max_debit_usd=2500`, `max_loss_usd=1200`, and `reviewer_max_contracts=2`, but a 2-lot far-DTE OTM profile needs ~$5k BP, which is inconsistent with the "$1k account" language in earlier briefs.

**Recommendation:** if promotion ever happens, start with `v2_28dte_atm` (1 contract, target 28 DTE, no BB gate on TP), not the pruned 55 DTE OTM operator profile.

---

## Phase C — Bugs & Edge Cases

### 3.1 Race / double-exit / partial fill

`lane_a_monitor.py:890-897` uses a deterministic `ref_id` per `(option_id, day, exit_reason)` to prevent duplicate exit orders across the four morning monitor runs. This is good.

However, `dry_run_exit_reviews_via_mcp` does not check the current open order state before placing. If a prior run's `place_option_order` is still pending fill (partial fill, market width), a subsequent run could issue a new sell-to-close for the same remaining quantity. The `ref_id` dedupes at the broker, but the local code does not wait for or read `get_option_orders` before placing.

**P1:** add a pre-place check of open orders for the same option.

### 3.2 Live exit fan-out across variant monitors

`lane_a_monitor.py:1240-1251` runs `dry_run_exit_reviews_via_mcp(all_alerts, classified)` for every monitor pass, including variant monitors. The code tries to skip the canary for variant monitors, but if there is a real RH position and an alert, **every active variant's monitor will call `review_option_order` (and potentially `place_option_order`) on the same underlying RH position under different variant rules**.

This is the v8 P0 #3 "live exit fan-out" issue. It is gated off today because `live_exits_enabled()` requires `agentic_account_id` + env flag, but if David ever turns on `XSP_LANE_A_LIVE_EXITS=true`, he will get N review/place calls per alert.

**P1:** only the baseline/promoted variant should issue live exit orders. Variant monitors should be paper-only.

### 3.3 Account pin empty → fail-closed?

`robinhood_mcp.py:215-228` `_live_flag` returns false unless the env/config flag is true AND `agentic_account_id` is non-empty. Good.

`config/rh_mcp.yaml:5` has `agentic_account_id: ""`. `env_example.txt:10` has `# RH_AGENTIC_ACCOUNT_ID=`. So default state is fail-closed. ✅

But `systemd/xsp-killer-lane-a-entry.service:15` sets `XSP_LANE_A_RH_MCP=true`. That means the entry cron will try to initialize the MCP adapter every run. Since `agentic_account_id` is empty and the token file is absent, `_load_token` will raise `RhMcpNotReady` and the live entry path will be skipped. That is safe, but it produces noisy logs and may leak the token path into logs.

### 3.4 Clock/session helpers vs `evaluate_exit_alerts` after `cc12ad5`

`lane_a_monitor.py:466-473` still defines `in_no_sell_window` and `in_sell_window`, but `evaluate_exit_alerts:537-628` never calls them. They are dead code for the production path. The fields still live in `LaneRules` and are written into the state/brief. This is a contradiction.

### 3.5 Paper vs live selector parity

`tests/test_operator_dte_stagger.py:86-143` verifies that `pick_expiration` and `RobinhoodMCPAdapter.select_entry_contract` share the same nearest-target logic. ✅

But paper strike selection uses `xsp_strike_to_spy_chain_strike` (SPY proxy), while live uses `get_option_instruments` against the real XSP chain. The DTE logic matches, but strike mapping may not, especially around half-steps (e.g., XSP 7505 vs SPY 750). This is a carry-over risk from prior audits.

---

## Phase D — RH Agentic Order Placement (David Setup)

### 4.1 What David must do before first read

1. **Create/fund a Robinhood Agentic account** on his primary RH login.
2. **Enable the MCP in Cursor desktop** (not server/Claude): `Settings → Tools & MCPs → https://agent.robinhood.com/mcp/trading`.
3. **Complete OAuth** in his local browser.
4. **Audit tool surface** and record in `config/rh_mcp_audit.md` (confirm `get_option_positions`, `get_option_chains`, `review_option_order`, `place_option_order` exist).
5. **Export the OAuth token** from Cursor's MCP store to the local token path.
6. **Set `RH_AGENTIC_ACCOUNT_ID`** in `.env` (from `get_accounts`).
7. **Set `XSP_LANE_A_RH_MCP=true`** and keep `XSP_LANE_A_RH_POLL=false`.

### 4.2 Before first write

1. **Confirm `agentic_account_id`** is pinned in `config/rh_mcp.yaml` or `.env`.
2. **Fund the Agentic account only** (isolated from primary RH book).
3. **Enable push notifications** in RH app.
4. **Set `XSP_LANE_A_LIVE_EXITS=true`** (for exits) or `XSP_LANE_A_LIVE_ENTRIES=true` (for entries), but never both at once on first test.
5. **Verify kill switches**: `XSP_LANE_A_KILL_SWITCH=true` or `.local/KILL_SWITCH` blocks all placement.
6. **Run a single-contract test** and confirm the order appears in the app.

### 4.3 Order path: `review` → `place`

`robinhood_mcp.py:1047-1056` and `lane_a_monitor.py:968-976`:

- `review_option_order` is called first.
- If `require_review_before_place=true` and the review grant matches, `place_option_order` is called.
- The adapter checks `kill_switch_engaged()`, `live_exits_enabled()` / `live_entries_enabled()`, `max_contracts_per_order`, and account pin before placing.

**Failure modes:**
- Token missing → `RhMcpNotReady`.
- Kill switch → `RhMcpKillSwitch`.
- Live flag false → `RhMcpLiveExitsDisabled`.
- Account mismatch → `RhMcpAccountRejected`.
- Quantity > `max_contracts_per_order` → `RhMcpError`.

### 4.4 Can writes ever hit a non-Agentic account?

`robinhood_mcp.py:595-607` rejects if the order's `account_number`/`account_id` does not match the pinned `agentic_account_id`. However, `_inject_account` (`robinhood_mcp.py:1035-1041`) injects the pinned account if none is present. Combined, the only way to hit a non-Agentic account is if the order explicitly carries a different account id. That is properly rejected.

**Residual risk:** if the adapter is initialized with a stale or empty `agentic_account_id` and `resolve_account_number` falls back to `get_accounts()` and selects the first account when only one exists (`robinhood_mcp.py:665-669`), a single-account user could accidentally trade the primary account. The code does try to detect "agentic" in nickname/type, but if Robinhood does not label it that way, fallback is unsafe.

**P1:** hard-fail if `agentic_account_id` is not explicitly set; do not fall back to single-account.

### 4.5 LIVE_ENTRIES / LIVE_EXITS / LIVE_VARIANT_ID fail-closed matrix

| Flag | `agentic_account_id` empty | `agentic_account_id` set + `LIVE_ENTRIES=false` | `agentic_account_id` set + `LIVE_ENTRIES=true` |
|---|---|---|---|
| `XSP_LANE_A_RH_MCP=false` | No MCP calls | No MCP calls | No MCP calls |
| `XSP_LANE_A_RH_MCP=true` | Reviews skipped, token error | Review-only canary, no place | Reviews + places allowed, gated by `LIVE_VARIANT_ID` |
| `XSP_LANE_A_KILL_SWITCH=true` | Blocks placement | Blocks placement | Blocks placement |

The matrix is fail-closed. ✅

**Hole:** `LIVE_VARIANT_ID` is only checked in `lane_a_entry.py:1189`. There is no equivalent exit-side `LIVE_VARIANT_ID` for variant monitors. As noted above, if live exits are on, all variants can review/place.

### 4.6 Options tool rollout risk

`docs/rh_mcp_runbook.md` and `rh_mcp_connection_brief.md` both note that Robinhood options tools are "rolling out." The adapter will fail with `RhMcpError` if `place_option_order` is not available. This is a known external dependency.

### 4.7 GO/NO-GO matrix for David's RH

| Mode | Status | Blockers |
|---|---|---|
| **Paper-only** | ✅ GO (current) | None; tests should pass first. |
| **MCP reads** | ⚠️ NO-GO until fixed | Token path not set, `.local` under OneDrive, Windows `fcntl` failures, no Task Scheduler. |
| **Live exits only** | 🚫 NO-GO | Variant-monitor fan-out, no Windows automation, no verified token store. |
| **Live entries** | 🚫 NO-GO | All of the above plus live entry allowlist must be set, buying-power verification, and single-contract test. |

---

## Phase E — Foreseeable Ops Issues

### 5.1 Local Windows vs `/opt/xsp-killer` Linux path assumptions

- `systemd/xsp-killer-lane-a-entry.service:7` and `lane-a-monitor.service:7` hardcode `WorkingDirectory=/opt/xsp-killer`.
- `scripts/lane_a_entry_cron.sh:4` hardcodes `XSP_KILLER_DIR="/opt/xsp-killer"`.
- `docs/rh_mcp_runbook.md:823` tells the operator to export the token to `/opt/xsp-killer/.local/...`.
- `robinhood_mcp.py:48` sets `ROOT = Path(__file__).resolve().parents[1]`, so relative paths like `.local/` will resolve to the Windows repo root if the code is cloned under `C:\Users\Owner\OneDrive\Desktop\xsp-killer`. That is good, but the docs and systemd do not match.

**P0:** David cannot run systemd on Windows. There is no Task Scheduler XML, PowerShell script, or `.bat` equivalent in the repo.

### 5.2 Token file permissions / OneDrive sync risk

`config/rh_mcp.yaml:7` and `robinhood_mcp.py:173` use `token_path: ".local/robinhood_mcp_token.json"`. With `ROOT` under the Windows repo, this becomes `C:\Users\Owner\OneDrive\Desktop\xsp-killer\.local\robinhood_mcp_token.json`.

**Problems:**
- OneDrive will sync the token file to the cloud if `.local` is inside the synced repo folder.
- Windows does not support Unix `mode 600`; NTFS permissions must be set via PowerShell/icacls.
- If the token is synced, it is a secret leak risk.

**P0:** move the token path outside OneDrive (e.g., `%LOCALAPPDATA%\xsp-killer\robinhood_mcp_token.json`) and document PowerShell permission lockdown.

### 5.3 Cron/timer load with 12 variants

`scripts/lane_a_entry_cron.sh:9` runs baseline entry then `lane_a_variants.py entry` for all active variants. With 12 variants and intraday mode for dip-swing, the system fires every 15 minutes during RTH. Each run fetches yfinance bars and SPY chain data. The in-process cache (`lane_a_ta.py:110-112`) mitigates this, but 12 variants × 4 intraday runs = 48 evaluation cycles per day, plus morning monitor runs.

**P1:** add observability (timer success/failure counts, per-variant runtime) and a circuit breaker if a variant fails repeatedly.

### 5.4 `fcntl` is Unix-only

`lane_a_monitor.py:185-190` and `lane_a_variants.py:137-141` use `fcntl.flock`. This will fail on Windows with `ModuleNotFoundError`. This means the state-file locking that protects `xsp-lane-a-state.json` and `xsp-lane-a-variants-state.json` will not work on David's Windows machine.

**P0:** replace `fcntl` with a portable lock or a Windows-specific fallback.

### 5.5 Missing artifacts

The following expected runtime artifacts are absent from the repo:
- `briefs/xsp-lane-a-monitor-latest.json`
- `briefs/xsp-lane-a-entry-latest.json`
- `briefs/xsp-lane-a-variants-scoreboard.json`
- `briefs/xsp-lane-a-paper-pnl-latest.json`
- `briefs/xsp-lane-a-entry-telemetry-latest.json`

Either the system has not been run at HEAD, or the paths are different. This blocks any promotion decision.

### 5.6 Test suite failing

`pytest_results.txt` reports:
```
(command failed: Command '['python3', '-m', 'pytest', 'tests/', '-q', '--tb=no']' returned non-zero exit status 1.)
```

Without the detailed failure log, we cannot classify which tests fail, but the fact that the full suite is red at HEAD is a P0. Likely contributors: Windows-only `fcntl`, missing yfinance, or stale fixture data.

---

## Ranked Findings

### P0 — Block promotion / block David live flip

1. **Test suite is red at HEAD.** `pytest_results.txt` reports non-zero exit. No live or promotion decision should be made until the suite is green.
2. **Windows runtime is not supported.** `fcntl` file locking and Linux systemd hardcoded paths will fail on David's Windows machine.
3. **OAuth token path lives under OneDrive.** `.local/robinhood_mcp_token.json` relative to the repo root will sync to the cloud and lacks Windows permission controls.
4. **Scoreboard/monitor/entry briefs are missing.** No empirical basis for promotion or trust.

### P1 — Before any live exit or Windows production

5. **Live exit fan-out across variant monitors.** If `LIVE_EXITS=true`, every variant monitor can review/place the same RH position. Only the promoted variant should issue live orders.
6. **No Windows automation.** No Task Scheduler, PowerShell, or `.bat` equivalents exist; the systemd units are Linux-only.
7. **Operator 55 DTE aspirational is pruned but still referenced.** Strategy docs and operator profile are inconsistent with the active 12-keeper grid.
8. **Legacy clock fields contradict `cc12ad5` behavior.** `sell_deadline_et`/`no_sell_end_et` still exist in YAML/rules but are ignored by `evaluate_exit_alerts`.

### P2 — Cleanup and observability

9. **Stale `strategy_diagnosis.md` (2026-06-29).** Does not reflect the dip-swing pivot or pruned far-DTE variants.
10. **No pre-place open-order check.** Partial fills could lead to duplicate close attempts.
11. **Single-account fallback in `resolve_account_number`.** Could trade the wrong account if Robinhood does not label the Agentic account clearly.

---

## David's RH Bring-Up Checklist (GO/NO-GO)

| Step | Action | GO Criteria |
|---|---|---|
| 1 | Fix tests and Windows portability | `pytest` green on David's machine |
| 2 | Move token out of OneDrive | Path under `%LOCALAPPDATA%`, locked down |
| 3 | Add Windows Task Scheduler jobs | Equivalent to systemd timers |
| 4 | Complete MCP OAuth + tool audit | `config/rh_mcp_audit.md` filled |
| 5 | Set `RH_AGENTIC_ACCOUNT_ID` | Confirmed Agentic account only |
| 6 | Run MCP read-only health check | `get_option_positions` returns expected data |
| 7 | Run review-only exit dry run | `review_option_order` succeeds, no place |
| 8 | Fix variant-monitor live exit fan-out | Only baseline/promoted variant can place exits |
| 9 | Single-contract live exit test | Confirmed fill, notification, P&L reconciliation |
| 10 | Single-contract live entry test | Confirmed fill, buying-power gate respected |

**Current status:** Steps 1–3 are not done. **NO-GO for all live modes.**

---

## Conclusion

HEAD has the right safety scaffolding on paper (`max_debit_usd`, exact allowlist, kill switch, separate live entry/exit flags), but the project is not in a promotable or live-flippable state. The immediate priorities are:

1. Make the test suite pass and remove Windows-only blockers (`fcntl`).
2. Move the Robinhood token path out of OneDrive.
3. Generate the missing scoreboard and briefs so there is real evidence.
4. Resolve the contradiction between the pruned operator 55 DTE aspirational and the active short-dated dip-swing grid.
5. Gate variant monitors so they cannot issue live orders.

Only after those are complete should David consider the MCP read-only, then review-only, then single-contract live exit path. Live entries remain a later phase.
```

---

## Executive Summary (8–12 lines)

- **Tests fail at HEAD** (`pytest_results.txt` exit status 1), so no promotion or live decision is defensible this week.
- **Operator 45–60 DTE OTM variants are pruned inactive** (`lane_a_variants.yaml:441-547`), leaving the active 12-keeper grid dominated by short-dated dip-swing variants — a material drift from the operator thesis.
- **Promotion is WAIT**: no scoreboard or briefs exist in the repo, and no active variant has cleared the 20-session / 20-trade gate.
- **David's RH setup is NO-GO for all live modes**: token path sits under OneDrive, systemd hardcodes `/opt/xsp-killer`, and `fcntl` file locking is Unix-only.
- **Live exit fan-out** is unfixed: if `LIVE_EXITS=true`, every variant monitor can review/place the same RH position (`lane_a_monitor.py:1240-1251`).
- **Docs are stale vs code**: `strategy_diagnosis.md` predates the dip-swing pivot, and the runbook targets cemini-prod Linux paths instead of David's Windows workspace.
- **Safety gates are structurally sound** (exact allowlist, `max_debit_usd`, kill switch, separate entry/exit flags), but the surrounding Windows/ops plumbing is not.
- **P0 actions:** fix tests, replace `fcntl`, move token out of OneDrive, generate missing scoreboard.
- **P1 actions:** add Windows Task Scheduler automation, gate variant-monitor live orders, update stale docs.
- **Bottom line:** keep `LIVE_ENTRIES=false` and `LIVE_EXITS=false`; paper-only until the P0/P1 blockers are cleared.

Now I need to compose the full report. Let me structure it carefully with all the findings.

Key findings I've identified:

1. **Tests failing at HEAD** - pytest_results.txt shows command failed with exit code 1. This is a P0 blocker for any promotion.

2. **Operator 45-60 DTE OTM variants are pruned inactive** - but the docs/strategy still reference them as aspirational. There's a contradiction between the active 12-keeper grid and the operator thesis.

3. **Far-DTE OTM stagger has DTE collision** - 55 and 60 target resolve to same expiry when 65 is outside dte_max (test_operator_dte_stagger.py documents this). This is a design flaw.

4. **Promotion readiness is far off** - need ≥20 sessions and ≥20 trades; active grid only has ~12 keepers, many are clones/dip-swing variants. The scoreboard is missing from repo.

5. **David's RH setup issues:**
   - systemd files hardcoded to /opt/xsp-killer (Linux) - won't work on Windows
   - token path .local/robinhood_mcp_token.json - OneDrive sync risk
   - runbook references /opt/xsp-killer and Linux paths
   - agentic_account_id empty in config
   - LIVE_ENTRIES=false, LIVE_EXITS=false - good fail-closed
   - But entry service has XSP_LANE_A_RH_MCP=true by default, which means it will try to read MCP even without token
   - No Windows automation (Task Scheduler, PowerShell) documented
   - Token file permissions (mode 600) not enforceable on Windows/OneDrive

6. **Contradictory docs vs code:**
   - docs/rh_mcp_runbook.md says "Export token to /opt/xsp-killer/.local..." but David is on Windows
   - env_example says RH_AGENTIC_ACCOUNT_ID is commented out but config/rh_mcp.yaml has agentic_account_id: ""
   - systemd says "MCP on so the live buy-to-open path is exercised" but LIVE_ENTRIES=false - this is contradictory: MCP on means it tries to connect but entries are disabled. Actually, this is intentional dry-run.
   - runbook says "Phase 2 - Live exits" and "Phase 2 - Live entries" both labeled Phase 2 - confusing
   - lane_a_rules.yaml says "exit anytime XSP session is open" but still has sell_eval_start_et/no_sell_start_et fields (kept for shadow compatibility)
   - strategy_diagnosis.md (2026-06-29) is stale - references old variants, doesn't mention dip-swing cluster

7. **Robinhood MCP safety:**
   - robinhood_mcp.py has good fail-closed gates: kill_switch, live_entries_enabled, live_exits_enabled, account pin check, max_contracts_per_order
   - _live_entry_safety_config has max_loss_usd default 150 (but config has 1200), max_debit_usd 2500, max_cost_frac 0.5
   - The default in code is 150 max_loss_usd but config has 1200 - discrepancy
   - place_option_order requires review before place (good)
   - But the reviewer is K37 shadow log-only (doesn't block)
   - If account pin empty, live_entries_enabled returns False (good)
   - Non-Agentic account rejection works if account field is set

8. **Windows-specific issues:**
   - fcntl file locking in lane_a_monitor.py and lane_a_variants.py - fcntl is Unix-only, will fail on Windows
   - Path handling with ROOT = Path(__file__).resolve().parents[1] - should work on Windows
   - .local directory in OneDrive - sync risk
   - Python shebang in scripts/lane_a_entry_cron.sh - bash script won't run on Windows
   - No Task Scheduler XML or PowerShell equivalent

9. **Scoreboard/artifacts missing:**
   - briefs/xsp-lane-a-monitor-latest.json not found
   - briefs/xsp-lane-a-variants-scoreboard.json not found
   - briefs/xsp-lane-a-entry-latest.json not found
   - This means the system hasn't been run or the artifacts are elsewhere

10. **Pytest failures:**
    - pytest_results.txt shows tests failed
    - Cannot determine exact failures without running, but likely related to Windows-only issues (fcntl) or missing dependencies

11. **K155-K162 spikes:**
    - macro_weather_notes, muse_spark_spike, fable_advisor_spike are opt-in NO-GO
    - Need to verify they don't affect entry/exit unless enabled
    - From code, they appear to be log-only extras

12. **Strategy after prune:**
    - Active keepers are now: v2_14dte_atm, v2_28dte_atm, v2_28dte_atm_stack3, v2_28dte_easy_tp, v2_28dte_green_day, v2_yellow_mid_bounce, v2_dip_swing_14dte, v2_dip_swing_21dte, v2_dip_swing_14dte_tp25, v2_dip_swing_14dte_tp60, v2_dip_swing_21dte_otm, v2_dip_swing_14dte_spread = 12
    - Many are clones/dip-swing variants
    - The operator 55 DTE aspirational is inactive
    - Promotion should be WAIT

13. **Paper vs live selector parity:**
    - Paper uses SPY chain proxy
    - Live uses RH MCP get_option_chains
    - Both use nearest-target logic (test verifies)
    - But paper strike uses xsp_strike_to_spy_chain_strike which may have rounding issues

14. **Live exit fan-out:**
    - Variant monitors all run run_monitor with write_paper_brief=False
    - Each variant monitor could potentially trigger dry_run_exit_reviews_via_mcp on the same RH position
    - The code checks _variant_monitor and _has_rh_positions to skip canary, but if there are RH positions and alerts, all variants will review them
    - This is the v8 P0 #3 live exit fan-out issue
