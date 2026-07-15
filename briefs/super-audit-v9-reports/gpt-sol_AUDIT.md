# cursor-audit · gpt-sol · xsp-killer · SUPER AUDIT v9

## Executive verdict

1. **Paper soak / measurement integrity — FAIL.** MCP-on paper exits work only while no eligible real RH position exists. Zero option marks disappear, and expired positions can become zero-PnL trades.
2. **Strategy coherence — WARN.** The 12-keeper grid is directionally reasonable, but pruning the 45–60 DTE thesis after zero entries is not evidence-based. The all-session exit change is operationally inconsistent with timers and TA behavior.
3. **Live RH flip readiness — FAIL.** Review outcomes are not enforced, malformed order effects bypass live flags and account-pin fail-closed behavior, and variant exit fan-out remains.
4. **Variant promotable this week — FAIL / WAIT.** No supplied scoreboard supports promotion, and several active variants remain structurally confounded.

## Phase A — Measurement

### P0 — zero marks become missing marks

`classify_position()` uses truthiness to select a mark:

- `xsp_killer/lane_a_monitor.py:309-312`
- `xsp_killer/lane_a_monitor.py:668-669`

A valid `mark_price=0.0` is discarded as false. Then `_position_return_pct()` returns `None`, and exit evaluation stops at `lane_a_monitor.py:559-561`. Consequences:

- A worthless option does not trigger stop loss.
- A DTE-0 swing position does not reach the near-expiry cut.
- Paper and live books can retain economically dead positions.

There is no zero-mark regression test.

### P0 — expiration accounting converts full losses into zero-PnL trades

`reap_expired_paper_positions()` records:

- `exit_pnl_usd=None`
- `exit_pnl_per_contract=None`

at `xsp_killer/lane_a_entry.py:1446-1465`.

The scoreboard then computes PnL with `float(value or 0)` while still counting every event as a trade:

- `xsp_killer/lane_a_variants.py:1339-1346`

Thus an expired long call may count as a zero-PnL trade instead of approximately the full debit loss. This biases average PnL, win rate denominator, and promotion metrics.

### P0 — v8 MCP paper-exit fix is incomplete

Paper positions are used only when no RH position was classified:

- `xsp_killer/lane_a_monitor.py:1200-1209`

Once one real eligible XSP position exists, every monitor evaluates that RH position and ignores its own paper book. Although `paper_positions_active` remains true at line 1253, alerts carry the RH UUID and cannot close synthetic paper IDs.

Current empty Agentic accounts conceal this defect. It appears immediately after the first real position is opened.

### P1 — evidence pack cannot establish current soak health

The pack reports missing:

- variant scoreboard
- variants state
- entry and monitor briefs
- health soak
- paper logs
- deployment status

`pytest_results.txt` only records a failed command without failure details. Therefore v9 cannot independently establish current sample count, ranking, post-epoch closes, or test health.

### Measurement improvements that did stick

- Paper exits can run with MCP enabled when RH returns no eligible position.
- Exact entry variant allowlisting is fixed.
- `max_debit_usd` is enforced in the orchestrated live-entry path.
- Stale paper marks suppress TP while still permitting SL.
- Scoreboard exposes 1× approximations and warns not to sum variants.

## Phase B — Strategy & logic

### Premarket spike versus all-session exits

Commit `cc12ad5` effectively supersedes the narrower `43fdda8` premarket window. Exit evaluation now runs whenever `xsp_session_open()` returns true.

Problems:

1. The baseline still requires upper-BB confirmation, but GTH SPY bars are usually stale or absent.
2. A stale `TaSignal` suppresses TP, while a TA exception sets `ta_signal=None`.
3. When `ta_signal=None`, the BB requirement fails open because it is enforced only when a signal object exists:

`xsp_killer/lane_a_monitor.py:581-588`

The same premarket TP may therefore be blocked on a clean stale-data result but allowed when TA raises an exception.

Active no-BB variants can sell GTH spikes, but baseline behavior is inconsistent and feed-failure-dependent.

### Session helper and timer disagree

`xsp_session_open()`:

- treats Friday 20:15 onward as open;
- treats Saturday morning as open;
- has no holiday calendar.

Evidence: `xsp_killer/lane_a_monitor.py:437-463`.

The monitor timer runs only Monday–Friday, every 15 minutes:

- misses Sunday 20:15–midnight GTH;
- runs Friday evening when the next valid GTH session generally does not exist;
- evaluates holidays as open.

The stated “whenever XSP session is open” invariant is therefore not operationally true.

### Pruning assessment

The 45/50/55/60 DTE OTM variants were pruned for “0 entries / starved,” not negative forward evidence. That is a capacity decision, not a strategy verdict. Keeping them disabled is reasonable while safety and measurement are broken, but declaring the operator thesis disproven is not.

A later retest should use one representative 50–55 DTE, one-lot shadow bucket rather than restoring four highly correlated buckets.

### Active-grid confounding

- `v2_28dte_atm` and `v2_28dte_atm_stack3` are identical until concurrency exceeds one.
- `v2_dip_swing_14dte_spread` still trades the naked long call; only spread economics are shadow metadata. Its realized trade path largely duplicates `v2_dip_swing_14dte`.
- Multiple dip-swing variants share entries and contracts, differing only in exit thresholds.

Promotion should be cluster-aware, not treat these as independent confirmations.

## Phase C — Bugs

### P0 — malformed `position_effect` bypasses both live switches and empty account fail-closed

Write gating computes:

- `needs_entry = "open" in effects`
- `needs_exit = "close" in effects or empty/blank`

at `xsp_killer/robinhood_mcp.py:556-577`.

For a typo such as `"opne"`, both values are false. The order bypasses both `LIVE_ENTRIES` and `LIVE_EXITS`. Because account presence is enforced inside those live-flag checks, this also bypasses the empty `agentic_account_id` fail-closed behavior.

The adapter can then send a reviewed order with no configured pin. Robinhood’s server-side Agentic restriction is the remaining boundary, not this code.

Required behavior: reject every effect not exactly `open` or `close`, reject empty legs, and require a non-empty pinned account independently of effect classification.

### P0 — review success is transport success, not order approval

Any successful `review_option_order` RPC creates an active grant:

`xsp_killer/robinhood_mcp.py:501-508`

The adapter never inspects:

- `isError`
- `order_checks`
- rejection status
- warnings
- review approval/confirmation state

The project’s own MCP audit demonstrates that `OPTION_NO_BID_PRICE` was returned and placement still succeeded (`config/rh_mcp_audit.md:130-147`).

Therefore “review before place” proves payload sequencing, not reviewer approval. Both entries and exits can place after an adverse review.

### P0 — live exit fan-out remains

Every active variant invokes `run_monitor()` independently. A variant monitor only skips MCP work when it has no alerts and no RH positions:

`xsp_killer/lane_a_monitor.py:1241-1251`

There is no exit-side `LIVE_VARIANT_ID` check. Every variant can evaluate the same RH position under different TP/SL rules and place an exit.

The deterministic `ref_id` mitigates only identical option/day/reason combinations. Different variants can emit different reasons, creating different order IDs.

### P1 — idempotency does not cover one overnight trading session

Exit IDs use the current calendar date:

`xsp_killer/lane_a_monitor.py:945`

A GTH session spans midnight, so the same unfilled exit signal receives two IDs before and after midnight. Different exit reasons also receive different IDs. There is no `get_option_orders` reconciliation before placement and no partial-fill handling.

### P1 — grant matching is incomplete

The grant key covers account, type, quantity, price, stop price, and normalized legs, but excludes `time_in_force`:

`xsp_killer/robinhood_mcp.py:339-353`

A reviewed GFD order can be changed to GTC before placement and still match. Grants also have no expiration time. `ref_id` exclusion is appropriate because Robinhood accepts it only on place.

### P1 — quantity validation is fail-open

At `robinhood_mcp.py:578-594`:

- malformed quantity defaults to `1.0`;
- zero, negative, and fractional quantities are not rejected;
- only the upper cap is checked.

The adapter should require a positive integer and valid positive integer leg ratios.

### P1 — paper/live selector parity is still broken

Paper `cheapest_near_atm` prioritizes minimum distance from ATM, using premium only as a tie-breaker. Live selection returns the globally cheapest ask:

`xsp_killer/robinhood_mcp.py:948-952`

For calls, this tends to select the highest OTM candidate rather than ATM. A live baseline can therefore buy a different strike from its paper shadow.

### P1 — required BB gate fails open on TA exception

As noted above, `require_upper_bb_for_take_profit` is ignored when `ta_signal=None`. A feed exception can cause a baseline exit that ordinary stale-data handling would block.

## Phase D — RH Agentic order placement

### David’s required setup

Before reads:

1. Complete OAuth using David’s own Robinhood identity.
2. Store the token outside OneDrive-backed paths where possible.
3. Run `get_accounts`; identify David’s Agentic account by metadata.
4. Pin that exact account ID locally.
5. Confirm options approval and XSP options tools.
6. Run health checks with all live flags false.
7. Verify audit records show David’s token subject and pinned account.

Before writes:

1. Resolve all P0 findings above.
2. Set exact `LIVE_VARIANT_ID` for entries and add equivalent exit ownership.
3. Exercise review-only on David’s account.
4. Verify adverse `order_checks` are rejected.
5. Add order/fill reconciliation and partial-fill handling.
6. Drill kill switch and OAuth disconnect.
7. Enable exits and entries separately.

### Empty account behavior

For correctly formed `open` and `close` orders, empty `agentic_account_id` currently disables placement. That part works.

It is not a complete invariant because malformed non-empty effects bypass both live checks and the account requirement.

### Can Claudio or a non-Agentic account be hit?

- The repository config is empty and therefore does not itself target Claudio.
- The supplied operational audit is explicitly Claudio/cemini-prod material and must not be reused as David’s setup.
- If Claudio’s token and matching Claudio Agentic ID are copied together, the code can place into Claudio’s Agentic account. It has no “David identity” assertion.
- The adapter does not verify account metadata is Agentic before writes; it relies on string pinning plus Robinhood’s server-side restriction.
- A malformed effect can bypass the local pin requirement entirely.

### Debit and exposure gates

The normal Lane A entry helper correctly checks:

- buying power;
- modeled stop loss;
- full debit;
- buying-power fraction;
- reviewer quantity and spread.

Evidence: `xsp_killer/lane_a_entry.py:1231-1328`.

However:

- direct `RobinhoodMCPAdapter.buy_to_open()` does not enforce debit, loss, or cost-fraction limits;
- malformed quantities weaken the adapter cap;
- there is no aggregate daily debit or open-position exposure cap;
- the reviewer can be disabled by environment;
- write calls do not enforce XSP/SPX instrument scope.

### Quote safety

Live position normalization carries no quote timestamp or staleness flag. Consequently:

- stale MCP marks are treated as fresh;
- a stale TP can place;
- stale SL uses a stale limit, which may not fill;
- no bid/ask spread check exists for exits;
- missing marks prevent signal generation before the market-order fallback can normally be reached.

### GO / NO-GO ranking

- **Paper-only:** WARN/conditional GO after zero-mark and expiry accounting fixes.
- **David MCP reads:** WARN/conditional GO after David OAuth, account verification, and token isolation.
- **Live exits only:** NO-GO.
- **Live entries:** NO-GO.
- **Any variant promotion:** NO-GO / WAIT.

## Phase E — Ops / foreseeable issues

### Windows incompatibility

David’s workspace is Windows, but both modules import `fcntl` unconditionally:

- `xsp_killer/lane_a_monitor.py:9`
- `xsp_killer/lane_a_variants.py:5`

The actual monitor and variant runtime will fail to import on native Windows. The runbook and services assume `/opt/xsp-killer`, bash, and systemd.

### Token storage

The default token path is inside this OneDrive-backed workspace. Git ignore does not prevent OneDrive synchronization. Use a non-synced user-local directory with Windows ACLs and point `token_path` there.

### Silent cron failures

Both cron wrappers append `|| true` to each Python command:

- `scripts/lane_a_monitor_cron.sh:8-11`
- `scripts/lane_a_intraday_cron.sh:12-14`

Monitor, variants, scoreboard, and sync can all fail while the service exits successfully.

### Configuration precedence

The systemd units load `.env` after hard-coded `Environment=` values. Effective live flags must be checked from the running service; the visible `LIVE_EXITS=false` line alone is not proof that writes are disabled.

### Documentation drift

The MCP audit and connection brief are Claudio/cemini-prod artifacts, while the v9 operator target is David on local Windows. They also contain stale assumptions about four morning monitor runs, one-contract caps, and old exit windows.

## Cross-auditor disagreement hooks

1. **Is empty account pin fully fail-closed?** Only for recognized effects. A malformed non-empty effect bypasses both live checks and account presence.
2. **Did `cf79281` fully fix paper exits under MCP?** Only while the RH book has no eligible real position; mixed paper/live operation remains broken.
3. **Is all-session exit strictly safer?** It reduces clock blindness but introduces GTH liquidity, stale-TA, holiday/calendar, and cross-midnight idempotency risk.

## Ranked patch backlog

### P0

1. Reject unknown/empty order effects and require a pinned account independently of live flags.
2. Validate review business outcome before issuing a one-use grant.
3. Prevent variant monitors from reading or writing the live RH book unless they own the promoted live position.
4. Evaluate paper and RH positions as separate collections.
5. Preserve zero marks and book expired long options as full-debit losses.

### P1

1. Add open-order/fill reconciliation, partial-fill handling, and trading-session-based idempotency.
2. Add grant TTL and include `time_in_force` in grant matching.
3. Require positive integral quantities and ratios.
4. Align live `cheapest_near_atm` with paper selection.
5. Make required BB confirmation fail closed.
6. Add quote timestamp, bid/ask, spread, and stale-limit handling for exits.
7. Replace the weekly session helper with an exchange calendar.
8. Add Windows-compatible locking or document Linux-only execution.
9. Stop masking cron failures; alert on failed monitor/scoreboard cycles.

### P2

1. Retest one representative 50–55 DTE operator-profile shadow after measurement repair.
2. Collapse confounded variant families in promotion reporting.
3. Separate David and Claudio runbooks and evidence.
4. Move OAuth tokens outside synced workspaces.
5. Rebuild the audit pack with actual test failures and current soak artifacts.

## Requested 10-line summary

1. **Paper measurement: FAIL** — zero marks vanish and expirations can record full losses as $0.
2. **Strategy: WARN** — 12 keepers are reasonable, but the far-DTE thesis was pruned without entry evidence.
3. **David live RH: FAIL / NO-GO** for both exits and entries.
4. **P0:** malformed `position_effect` bypasses live flags and empty account-pin fail-closed (`robinhood_mcp.py:556-577`).
5. **P0:** any transport-successful review creates a place grant; warnings/rejections are ignored (`robinhood_mcp.py:501-508`).
6. **P0:** every variant can evaluate/place against the same RH position (`lane_a_monitor.py:1241-1251`).
7. **P0:** one RH position suppresses all variant paper-book evaluation (`lane_a_monitor.py:1200-1209`).
8. **P1:** stale quotes, cross-midnight IDs, and absent fill reconciliation permit duplicate or unfilled exits.
9. **P1:** live cheapest-strike selection diverges from paper (`robinhood_mcp.py:948-952`).
10. **Promotion: WAIT** — no reliable scoreboard or supplied passing test run supports promotion.

**Evaluating system behavior**
