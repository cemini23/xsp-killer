# Plan — prod briefs → XSP Killer (2026-07-28)

**Status:** DONE (Cursor)

**Hard stops:** `LIVE_*` false; no integral solvers; no strategy gate flips.

## Brief triage

| Brief | Action |
|-------|--------|
| **K198** IV concavity + Macro Korea/WTI/FOMC | CODE: log-only `k198` (mirror K196). Brief says "**No code**". |
| K196 / earlier | Already shipped (`473e957`) |
| `pm-2026-07-28_k198-*` | Skip — PM/Kalshi |

## Implement
`k198:` YAML + loader/merge + tests. Event-day smile concavity watch; FOMC overnight tight; no Korea/AI chase alone.
