# Plan — cursor-audit money-path hardening (2026-07-20)

**Status:** IN PROGRESS (Cursor; no Grok)  
**Source:** `briefs/2026-07-20_cursor-audit-architecture.md`  
**Hard stops:** Do not flip `LIVE_*`; keep paper soak safe; fail closed.

## Scope (all audit fix-order items)

| # | Fix | Where |
|---|-----|--------|
| 1 | Human two-key ack at adapter chokepoint | `robinhood_mcp._enforce_write_gates` |
| 2 | Nested review unwrap + explicit approve | `_review_outcome_approved` |
| 3 | Only `buy+open` / `sell+close`; reject bad qty; token↔account bind before place | `_enforce_write_gates` |
| 4 | No market close fallback (fail closed; opt-in env) | `_build_close_order` |
| 5 | Live exit ownership + live entry RH open dedupe | monitor + entry |
| 6 | Intraday respect `max_open_positions` (don't return early when room remains) | `lane_a_intraday` |
| 7 | Adversarial tests | `test_robinhood_mcp`, monitor/entry/intraday |

## Design notes

- Strip internal `xsp_killer_variant_id` from order args before MCP HTTP.
- Adapter human gate: require `human_variant_review_allows(variant)` where variant comes from popped metadata or `live_variant_id()`.
- Nested review: recursively unwrap `data` / merge rejection signals; require explicit `approved is True` OR (`ok is True` and no negatives) after unwrap — prefer requiring positive signal when present.
- Market fallback: raise/skip unless `XSP_LANE_A_ALLOW_MARKET_EXITS=true`.
- Exit ownership: only act on RH option IDs present in this system's open paper positions for the promoted variant (or tagged `live_option_id` / `instrument_id` on paper rows). Skip foreign book positions.
- Entry dedupe: before live buy, if RH already has open XSP/SPX calls matching, skip (in addition to ref_id).
- Intraday: if `open_n > 0`, still run monitor for exits; only skip entry attempt when `open_n >= max_open_positions`.

## Verify
- Focused pytest + ruff on touched files
- Premium-model `/check-work` style audit (opus) readonly against the diff
- Commit + push + CI green
