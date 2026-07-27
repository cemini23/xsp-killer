# Plan — prod briefs → XSP Killer (2026-07-27)

**Status:** DONE (Cursor)

**Sources scanned:** `/opt/cemini/briefs/*2026-07-2[5-7]*` + `/opt/cemini/briefs/xsp-*`; `/opt/xsp-killer/briefs/*`.  
**Hard stops:** `LIVE_*` false; no new RH sleeve; no integral solvers; no strategy gate flips; no GuruWatcher code in this repo.

## Brief triage

| Brief | Action |
|-------|--------|
| **K196** `xsp-2026-07-27_k196-macro-hedging-attention-vol.md` | CODE: log-only `k196` extras (mirror K195). Brief says "**No code**" → weather notes only. |
| `xsp-2026-07-27_macro-charts-watch-discord-prod.md` | Sync brief only — GuruWatcher on cemini-prod (alert-only); not xsp-killer CODE. |
| K195 / earlier weather | Already shipped (`fcaebec`) |
| `pm-2026-07-27_k196-kalshi-nevada-geofence` | Skip — PM/Kalshi |

## Implement
`k196:` YAML + `load_k196_notes` + merge + tests. Lane A overnight tight; Lane B residual delta tolerate; attention SV Watch only.
