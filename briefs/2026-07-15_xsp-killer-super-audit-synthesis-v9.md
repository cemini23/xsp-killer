---
title: XSP Killer — SUPER AUDIT v9 Synthesis (post-prune + David RH readiness)
type: brief
tags: [super-audit, xsp-killer, cursor-audit, robinhood-agentic, david-rh, prod-ship]
created: 2026-07-15
updated: 2026-07-15
target: cemini-prod /opt/xsp-killer + David local RH bring-up
---

# XSP Killer — SUPER AUDIT v9 Synthesis (post-prune + David RH readiness)

**Date:** 2026-07-15 · **HEAD audited:** `cc12ad5` · **Pack:** `reports/gap-audit/pack-xsp-killer-v9/`  
**Scope:** accuracy / strategy / logic / bugs / RH Agentic order placement for **David's** Robinhood (not Claudio cemini-prod). Post-v8 landings + prune + session-open exits.

**Panel (6 attempted · 5 completed reports):**

| Slot | Channel | Model | Report |
|------|---------|-------|--------|
| 1 | Cursor | **Fable 5** (`claude-fable-5-thinking-high`) | `briefs/super-audit-v9-reports/fable-5_AUDIT.md` |
| 2 | Cursor | **GPT SOL** (`gpt-5.6-sol-medium`) | `briefs/super-audit-v9-reports/gpt-sol_AUDIT.md` |
| 3 | Cursor | **Kimi K2.7** (`kimi-k2.7-code`) | `briefs/super-audit-v9-reports/kimi-k2.7_AUDIT.md` |
| 4 | API | **GLM 5.2** (OpenRouter) | `briefs/super-audit-v9-reports/glm-5.2_AUDIT.md` |
| 5 | API | **DeepSeek Reasoner** | `briefs/super-audit-v9-reports/deepseek-reasoner_AUDIT.md` |
| 6 | API | **OpenRouter Fusion** | **Incomplete** — HTTP 200 but empty `content` after burning completion budget / tool_calls (full + slim packs). Probe OK on tiny prompts. Do not treat Fusion as a completed vote. |

**Prior:** `briefs/2026-07-09_xsp-killer-super-audit-synthesis-v8.md` · claimed P0 fixes in `cf79281`.

> **Overall for Claudio + David:** **REWORK / NO-GO on any live RH write.** Paper keep soak. Do not set `LIVE_ENTRIES` or `LIVE_EXITS`. David's OAuth bring-up is fine for **reads only** after token is moved out of OneDrive — **not** for placement until P0s below land.

---

## Executive verdict (panel consensus)

| # | Question | Verdict | Basis |
|---|----------|---------|-------|
| 1 | Paper soak / measurement | **WARN → FAIL if trusting promotion math** | v8 debit/allowlist/mark-guard code fixes **stuck**. Pack built on Windows clone: **scoreboard / paper logs / telemetry missing**; pytest runner failed (`python3`/suite). GPT SOL: zero-mark + expiry accounting bias. Fable: mixed RH+paper path still starves paper exits. |
| 2 | Strategy (prune + new exits) | **WARN** | 12-keeper prune OK for capacity; **45–60 OTM operator stagger not refuted** (starved / wrong exit regime). Active grid ≠ operator ~55 DTE aspirational. Premarket / session-open exits directionally fine; GTH liquidity + paper marks unmeasurable overnight. |
| 3 | Live RH flip (David) | **FAIL (unanimous among completed auditors)** | Fan-out still open; selector parity broken; Windows/`fcntl`/OneDrive blockers; review grants = transport not approval (SOL); malformed `position_effect` can skip live flags (SOL). |
| 4 | Promotable this week? | **NO / WAIT** | No verifiable `edge_confirmed`; promotion gates ≥20 trades unreachable near-term for swing holds. |

**DeepSeek alone** rated paper **OPERATIONAL** and Adapter “sound” without weighting SOL/Fable code-cited holes — resolve as **conflict → trust code-cited majority**.

---

## Strong consensus (≥4 of 5 completed)

1. **Do not enable live entries or exits** on David's (or Claudio's) RH until exit fan-out is gated.
2. **David's account must use David's token + David's Agentic pin** — never reuse cemini-prod/Claudio token or account ID.
3. **v8 P0 #3 (exit fan-out) still open** — `cf79281` only skipped canary when no alerts/positions; with a real RH position every variant monitor can review/place under different TP/SL (`lane_a_monitor.py` ~1240–1251).
4. **Default `cheapest_near_atm` live ≠ paper** — live min-ask tends one-step OTM; paper prefers nearest ATM (`robinhood_mcp.py` ~948 vs `lane_a_entry.py` ~311).
5. **Token under OneDrive repo path is a secret-sync risk**; prefer `%LOCALAPPDATA%\xsp-killer\…`.
6. **`fcntl` makes monitor/variants non-importable on native Windows** — run soak/live on Linux VPS (or port locks) for production; health script may still run.
7. **Rebuild pack / scoreboard from VPS** before any soak-number claim.

---

## Unique / high-value (investigate even if single auditor)

| Auditor | Finding | Evidence |
|---------|---------|----------|
| **GPT SOL** | Malformed non-empty `position_effect` (e.g. typo) can make `needs_entry`/`needs_exit` both false → **bypasses LIVE_* and pin-gated flags** | `robinhood_mcp.py:556-577` |
| **GPT SOL** | Successful `review_option_order` RPC creates place grant **without** inspecting review warnings / rejection / `order_checks` | `robinhood_mcp.py:501-508` + prior `config/rh_mcp_audit.md` |
| **GPT SOL** | `mark_price=0.0` treated falsy → no exit; expired paper can score as **$0 PnL trade** | `lane_a_monitor.py` classify / `lane_a_entry.py` reap / `lane_a_variants.py` scoreboard |
| **Fable** | Mixed book: once any RH position classified, **paper books don't generate exit alerts** (`if not classified and paper…`) — reopens v8 paper-exit issue the day first live fill lands | `lane_a_monitor.py:1206` |
| **Fable** | `conductor_shadow` day-after −1.5% SPY block may **starve DIP_BOUNCE** cluster (worth measuring) | `conductor_shadow.py:33-37` |
| **Fable** | Unfilled GFD exit: same `ref_id` same day blocks reprice → stop can **silently fail all session** | `lane_a_monitor.py:892-919` |
| **Kimi / GLM** | Docs/systemd still `/opt/xsp-killer`; no Windows Task Scheduler path | `deploy/systemd/*`, runbook |
| **GLM** | Far-DTE prune done **before** `cc12ad5` exit regime — operator 55 DTE thesis untested under new exits | prune commits vs `cc12ad5` |

---

## Conflicts (resolve before ship)

| Topic | Soft take | Hard take | Resolution |
|-------|-----------|-----------|------------|
| Paper integrity | DeepSeek OPERATIONAL | SOL FAIL / Fable WARN+FAIL | **WARN pending VPS artifacts;** treat SOL measurement bugs as P0 before promotion math |
| Was 45–60 prune correct? | DeepSeek yes (old negatives) | Fable/GLM premature | **Capacity prune OK; thesis untested — one 50–55 DTE bucket later** |
| Empty pin fail-closed? | Most: yes via `_live_flag` | SOL: not for malformed effects | **Add explicit reject unknown effects + pin always required** |

---

## David's RH bring-up (post-audit plan — GO/NO-GO)

| Mode | Status | Preconditions |
|------|--------|----------------|
| Paper-only | **GO** (VPS preferred) | Rebuild scoreboard; prefer green pytest |
| MCP **reads** on David | **Conditional GO** | David's OAuth; token **outside OneDrive**; pin David's Agentic ID; `rh_mcp_health.py` HIGH; live flags **false** |
| Live **exits** | **NO-GO** | Fan-out fix + review outcome validation + reprice policy + pin∈accounts(token) |
| Live **entries** | **NO-GO** | Above + selector parity + `edge_confirmed` + `LIVE_VARIANT_ID` exact |
| Promote any variant this week | **NO** | — |

**Do next (David setup, not code yet):**
1. Open Agentic account on **David's** RH; desktop OAuth to `https://agent.robinhood.com/mcp/trading`.
2. Export token to non-synced path; set `token_path` + `RH_AGENTIC_ACCOUNT_ID` for **David only**.
3. Keep `LIVE_ENTRIES=false`, `LIVE_EXITS=false`, kill switch available.
4. Run read-only health — **stop**. Placement waits for P0 patches below.

---

## Ranked patch backlog

### P0 — block live writes / untrustworthy promotion

1. **Exit-side live ownership** — only baseline/promoted variant may call place on RH positions (exit `LIVE_VARIANT_ID` or skip MCP writes on `_variant_monitor`).
2. **Reject unknown `position_effect`**; require pinned account independently of LIVE flags.
3. **Validate review business outcome** before issuing place grant (warnings/rejections/order_checks).
4. **Always evaluate paper books separately** from RH classification (`lane_a_monitor.py:1206`).
5. **Fix zero-mark + expired-paper PnL accounting** (SOL).
6. **Move OAuth token off OneDrive**; document David's path (not Claudio `/opt` copy-paste).
7. **Align live `cheapest_near_atm` with paper** (or re-soak under live semantics).
8. **Rebuild pack/scoreboard on VPS**; get pytest green (or document Windows runner: `python` not `python3`).

### P1 — before first live exit test

9. Cancel/replace or session-based `ref_id` for unfilled stops; partial-fill residual.
10. Grant TTL + include `time_in_force` in grant key.
11. Portable locking (`portalocker`/`msvcrt`) or document Linux-only runtime.
12. Pin ∈ `get_accounts(token)` health assertion (prevent Claudio/David mixups).
13. GTH exits: price off bid / wider spread veto on paper and live.
14. Measure `conductor_shadow` vs DIP_BOUNCE starvation.

### P2

15. Collapse confounded clone families in promotion reporting; re-enable **one** 50–55 DTE OTM shadow after measurement repair.
16. Separate David vs Claudio runbooks; refresh `strategy_diagnosis.md`.
17. Fix Fusion API runner for long prompts (empty content / tool_calls) before next council.

---

## Recommended fix order (Claudio)

1. P0 #1 fan-out + P0 #2/#3 MCP write gates (safety).
2. P0 #4/#5 measurement integrity.
3. P0 #7 selector parity.
4. P0 #8 VPS pack rebuild — then re-score promotion claims.
5. David read-only RH bring-up (ops) in parallel after token path fixed.
6. Only then: staged LIVE_EXITS canary (1 contract) → LIVE_ENTRIES.

---

## Pack / tooling notes

- Prompt: `prompts/xsp_killer_super_audit_v9.md`
- Builder/runner updated for v9 + DeepSeek registry: `scripts/build_xsp_killer_super_audit_pack.py`, `scripts/run_xsp_killer_super_audit_api.py`
- Windows: set `PYTHONIOENCODING=utf-8` (print arrows previously marked OK calls as errors despite `.md` written)

---

**Overall:** **REJECT live ship · SHIP-WITH-FIXES for paper+read path** — one paragraph: HEAD has real safety scaffolding (debit caps, exact entry allowlist, kill switch, separate entry/exit flags), but unfixed exit fan-out, review/effect gate holes, paper/live selector mismatch, and David Windows/OneDrive ops make any live RH placement premature. Next session: patch P0s, VPS evidence pack, then David OAuth reads only.

**Prior synthesis:** `briefs/2026-07-09_xsp-killer-super-audit-synthesis-v8.md`
