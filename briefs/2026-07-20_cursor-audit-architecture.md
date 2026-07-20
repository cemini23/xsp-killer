# Cursor audit — xsp-killer architecture (2026-07-20)

**Mode:** `architecture`  
**Roles → models:** agentic-reasoning → `claude-opus-4-8-thinking-high`, third-lens → `gemini-3.1-pro`, code-implementation → `gpt-5.6-sol-medium` *(mid-tier fallback; `gpt-5.6-codex-high` unavailable)*  
**HEAD:** `f57dc96`  
**Skill:** OSINT wiki `/tmp/llm-wiki-by-cemini/.cursor/skills/cursor-audit` v1.3.0  
**Question:** Fail-closed for paper soak / Phase-1 RH MCP dry-run — highest money-path risks before any `LIVE_*` flip?

## Consensus (≥2 auditors agree)

- **Current deploy is paper/dry-run safe** while `LIVE_ENTRIES`/`LIVE_EXITS` stay false (systemd + adapter I2–I8). Continue soak OK.
- **Human two-key ack is caller-side only**, not in `_enforce_write_gates` — `require_human_variant_review` is effectively dead at the money chokepoint ([opus](d5b47c53-fedd-47af-938f-1f9d0720b786), [sol](dbf88e23-393f-415a-aeb1-0d79347c1a2b)). Move into adapter before LIVE.
- **Adapter trusts callers too much** for LIVE: human gate, side↔effect pairing, qty floor, token/account binding as placement prerequisite.
- Debit-spread / weather notes remain correctly log-only / shadow (positive).

## Unique (single auditor — still investigate)

- [opus] Live exits variant-scoped but iterate whole RH book — no ownership/provenance check before close.
- [opus] Live entry dedupe leans on paper `entry_log` + `ref_id`; soak reset clears log.
- [opus] Baseline `run_monitor` RMW not atomic vs variants lock (paper integrity only).
- [gemini](`de948a5f-e90f-47bf-8a63-a6ef969dd061`) Market fallback when `close_limit_price` is None (`lane_a_monitor.py:1171`) — real only if LIVE_EXITS on.
- [gemini] SL fires on wide/stale marks by design (TP vetoed) — paper/LIVE economics risk.
- [gemini] `run_intraday_cycle` returns after monitor when `open_n > 0`, blocking further intraday entries (breaks stacking if `max_open_positions > 1`).
- [sol] Nested review payload `{"data":{"ok":false}}` can mint grant — `_review_outcome_approved` top-level only (`robinhood_mcp.py:496-535`).
- [sol] `.env` EnvironmentFile can override systemd LIVE flags — separate secrets from LIVE controls.
- [sol] Phase-1 review canary is monitor-path; entry service short-circuits before review when `LIVE_ENTRIES=false`.

## Conflicts (Glasswing)

| Topic | opus | gemini | sol | Resolution |
|-------|------|--------|-----|------------|
| Overall for paper soak | PASS+warn | FAIL | WARN | **SHIP paper soak** — FAIL findings are LIVE-path execution quality, not current false flags. Parent verified market fallback + SL-on-wide exist but gated by LIVE_EXITS. |
| Market/SL severity | (not top) | critical | (not top) | Treat as **warn-before-LIVE**: fail-closed on missing limit; reconsider SL on wide spreads. |
| Human gate severity | warn | — | critical | Agree on defect; severity **critical before LIVE**, warn while LIVE false. |

## Recommended fix order (before any LIVE_* flip)

1. Enforce `require_human_variant_review` inside `_enforce_write_gates` / `place_option_order`.
2. Unwrap nested review `data`; require explicit positive approval before grant.
3. Validate only `buy+open` / `sell+close`; reject bad qty; bind token↔pinned account at place time.
4. Fail closed on missing close limit (no market fallback) unless operator opts in.
5. Ownership/provenance for live exits; live open-position count for entry dedupe.
6. Fix intraday early-return if stacking (`max_open > 1`) is desired.
7. Expand adapter adversarial tests (nested reject, side/effect, qty, human at adapter).

## Verdict rollup

| Model | Verdict |
|-------|---------|
| claude-opus-4-8-thinking-high | PASS (with warnings) |
| gemini-3.1-pro | FAIL |
| gpt-5.6-sol-medium | WARN |

**Overall: SHIP-WITH-FIXES** — safe to continue paper soak and Phase-1 review-only MCP with `LIVE_*` false. Do **not** flip LIVE until adapter-layer human/review/semantics hardening (items 1–3+) lands and is re-audited.
