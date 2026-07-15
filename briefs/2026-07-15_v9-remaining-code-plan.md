# Plan — v9 remaining CODE backlog (Grok CLI)

**Date:** 2026-07-15 · **Repo:** `/opt/xsp-killer` · **Hard stop:** keep `LIVE_ENTRIES=false` / `LIVE_EXITS=false`

## Goal

Ship all remaining **CODE** items from super-audit v9 (P1 #11/#13/#14 + P2 #15–17). Ops items stay on David's tomorrow list.

## Scope

| # | Item | Primary files |
|---|------|----------------|
| P1 #11 | Real portable locks (`portalocker` / `msvcrt`), not Windows no-op | `xsp_killer/fs_lock.py`, deps, tests |
| P1 #13 | GTH exits: price off bid + wide-spread veto (paper + live) | `lane_a_monitor.py`, `spy_quote.py`, rules YAML, tests |
| P1 #14 | Measure `conductor_shadow` vs DIP_BOUNCE starvation | counter/telemetry + brief/script or scoreboard field |
| P2 #15 | Collapse confounded clones in promotion; re-enable **one** 50–55 DTE OTM shadow | `lane_a_variants.py`, `config/lane_a_variants.yaml` |
| P2 #16 | Separate David vs Claudio runbooks; refresh strategy diagnosis | `docs/rh_mcp_runbook.md`, new David/Claudio docs, `docs/lane-a-strategy-diagnosis.md` |
| P2 #17 | Fix Fusion API runner (empty content / tool_calls on long prompts) | `scripts/run_xsp_killer_super_audit_api.py` |

## Implementation notes

### P1 #11 — locks
- Prefer `portalocker` cross-platform; fall back `fcntl` then `msvcrt` (Windows).
- Never silent no-op if a lock backend exists; log loud if lock truly unavailable.
- Add `portalocker` to package deps if present; keep import optional-with-clear warning.

### P1 #13 — GTH liquidity
- When `xsp_session_open` but not RTH (before 09:30 / after 16:15 ET): exit limit uses **bid** (not mid/mark) when bid available.
- Wide-spread veto: if `(ask-bid)/ask >` threshold (default **0.25**, match reviewer), skip TP/SL **placement** for take-profit; allow stop-loss still (risk) but prefer bid.
- Apply to paper close marks and live `_build_close_order`.
- Tests for GTH bid pricing + wide-spread veto.

### P1 #14 — conductor_shadow starvation
- When entry skip reason buckets to `conductor_shadow` and variant `regime_gate == DIP_BOUNCE`, increment a dedicated counter (JSONL or scoreboard telemetry).
- Small script or scoreboard field: `conductor_shadow_skip_count` vs `dip_bounce_sessions` so starvation is measurable.
- Unit test the counter wiring (no live soak required).

### P2 #15 — clones + one 50–55 shadow
- Promotion summary: group/collapse rows sharing identical realized book / `track_family` clones; document which ids are confounded.
- Re-enable **exactly one**: `v2_dip_swing_50dte_otm` **or** `v2_dip_swing_55dte_otm` (prefer **55** as operator aspirational ~55 DTE). Leave other far-DTE OTM false.
- Comment why in YAML.

### P2 #16 — runbooks
- Split RH ops: Claudio VPS (`/opt/xsp-killer`) vs David Windows (`%LOCALAPPDATA%\xsp-killer`, not OneDrive).
- Refresh `docs/lane-a-strategy-diagnosis.md` for dip-swing + session-open exits + prune state.

### P2 #17 — Fusion runner
- Handle `message.content` null/empty when `tool_calls` present: strip plugins / disable tools, or extract text parts; retry once without fusion plugins if empty.
- Prefer `response_format` / force text-only; raise clear error with finish_reason + usage.

## Done when

1. Targeted tests green for locks, GTH veto, shadow counter, fusion content extraction.
2. `v2_dip_swing_55dte_otm` active (or documented 50).
3. Docs updated; backlog status brief refreshed.
4. Commit ready (do **not** push unless asked; do **not** flip LIVE_*).

## Out of scope

- David OAuth / UW key / OneDrive token move (ops).
- Enabling live RH writes.
