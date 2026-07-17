# Plan — History → Lane A rules (Friday flatten + size + spread posture)

Author: Cursor plan for Grok CLI. Date: 2026-07-17.
Source: Claudio RH realized PnL dump (`.local/rh_history/claudio_full_history_*.json`).

## 0. Context

Live history (267 PnL trades, ~−$2.4k): ~50% win rate; losers larger than winners.
Dominant damage = **Friday / ~16:00 ET expiration wipeouts** (`price=0`, large qty).
Style = single-leg long options, ~1-day median hold. Best names liquid directional;
worst = OPEN/GEO/TSLA/MSTR/QQQ lottery tickets.

Agentic XSP lane already size-caps at 1 contract. Highest-leverage code change:
**never gift long premium into Friday expiration**, keep size hard-capped, keep
spreads research/shadow (not live).

## 1. Goal / Done / Non-goals

**Goal:** Encode history lessons into Lane A monitor/entry so paper + future live
exits flatten Friday risk and entries refuse Friday opens — without flipping LIVE_*.

**Done when:**
1. New exit reason fires on Friday at/after configurable ET clock (default 15:45).
2. Entry path refuses new paper/live opens on Friday (ET calendar).
3. Size stays hard-capped at 1 contract for Agentic/paper defaults (assert + test).
4. Debit-spread remains shadow/research only (`active: false` / no place-path wire).
5. Tests cover flatten + Friday entry block; focused pytest green.
6. Local commit (no push unless asked). `LIVE_*` stay false.

**Non-goals:**
- Enabling LIVE_ENTRIES / LIVE_EXITS
- Wiring debit spreads into place_option_order
- Multi-ticker sleeves (OPEN/GEO/etc.)
- Changing Agentic account pin / OAuth

## 2. Design

### A) Friday flatten (exit)
Add to `LaneRules` / `config/lane_a_rules.yaml` → `exit:`:
- `friday_flatten_enabled: true`
- `friday_flatten_et: "15:45"`  # ET; fire when session open and clock >= this on Friday

In `evaluate_exit_alerts`:
- If enabled and `now_et` is Friday and local time >= `friday_flatten_et` and XSP session open → emit exit with reason **`friday_flatten`** (add to `ExitReason` Literal + `exit_reasons` YAML list).
- Precedence: after SL (risk first), before or alongside hold_cap — prefer firing even if TP not hit (history: expiration wipeouts).
- Message must mention Friday flatten / expiration risk.

Also: if `pos.dte == 0` on any weekday during session → treat as expiration risk (optional reuse `time_stop` or same `friday_flatten` only on Friday; for DTE0 any day use existing `max_hold_dte` / add `expiry_day_flatten` only if cheap — prefer **Friday rule + existing near-expiry cut**; do not overbuild).

### B) No Friday entries
In paper entry decision + live entry gate (lane_a_entry / entry cron path):
- If ET weekday == Friday → skip / veto with reason `friday_no_entry` (log-only string in decision).
- Do not place paper or live opens Fridays.

### C) Size discipline (assert, don’t loosen)
- Keep `paper_entry.quantity: 1`, `max_open_positions: 1`.
- Keep `rh_mcp max_contracts_per_order: 1` for Agentic path (or document if config says 2 for reviewer — **do not raise** live lot size; if `reviewer_max_contracts: 2`, leave comment that history prefers 1 and Agentic stays 1).
- Add a focused test that paper quantity resolves to 1.

### D) Spread posture (no live wire)
- Document in plan Status + short comment in `lane_a_rules.yaml` or inactive variant:
  debit spreads remain Stage B / `debit_spread_shadow` only.
- Do **not** call place for spreads.

### E) Optional hold cap (small)
Set base or comment: history median hold ~1d → recommend `max_hold_sessions: 3` on an **inactive** research note OR enable on base only if tests expect 0 today.
**Prefer:** leave base `max_hold_sessions: 0` unchanged; add YAML comment + optional inactive variant override `max_hold_sessions: 3` for soak — avoid surprising active soak mid-day unless tests already tolerate it.
Safer: enable Friday rules only this pass; hold_cap as documented follow-up.

## 3. Files

**Edit:**
- `xsp_killer/lane_a_monitor.py` — LaneRules fields, ExitReason, evaluate_exit_alerts
- `xsp_killer/lane_a_entry.py` — Friday entry veto
- `config/lane_a_rules.yaml` — friday_flatten_* + exit_reasons + comments
- `tests/test_lane_a_monitor.py` (or new `tests/test_lane_a_friday_rules.py`)
- `tests/test_lane_a_entry.py` if present

**Create:**
- `tests/test_lane_a_friday_rules.py`
- Update this plan Status → DONE

**Do not touch:** systemd LIVE_* flags, tipdrop secrets, debit-spread place path.

## 4. Tests
1. Friday 15:44 ET → no friday_flatten; 15:45 ET → friday_flatten alert
2. Thursday 15:45 → no friday_flatten
3. Friday entry window → decision skipped with friday_no_entry
4. Non-Friday entry still allowed (other gates permitting)
5. SL still beats friday_flatten when both would apply (SL first)
6. YAML loads new fields; LIVE flags untouched

## 5. Hard constraints
- LIVE_ENTRIES / LIVE_EXITS stay false
- No secrets in git
- Match repo style; small diffs
- Commit locally when green; **do not push** unless asked

## 6. Phases for Grok
1. Rules + evaluate_exit_alerts + tests 1,2,5
2. Entry Friday veto + tests 3,4
3. YAML + size assert test + plan Status DONE
4. pytest focused + local commit

## 7. Status
- [x] Plan written
- [x] Implemented by Grok
- [x] Tests green
- [x] Local commit
  DONE 2026-07-17 — friday_flatten exit + friday_no_entry; paper qty=1; LIVE_* untouched.
