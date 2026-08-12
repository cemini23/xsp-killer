# Plan — prod briefs → XSP Killer (2026-08-11)

**Status:** IMPLEMENTED IN CURSOR (+ GPTSOL debug)
**Lane:** hard (log-only weather)

## CODE
- `xsp-k231-donny-meta-rea.md` → k231 weather (Fed/Warsh week + META watch + REA sentiment)
- `xsp-k232-wublock-july-spot-volume.md` → k232 weather (July spot volume contraction)
- Overnight ends `keep_tight_vs_k231`

## Skip
- `pm-k231-flightaware-kalshi.md` (PM)
- Harness K261–K269 / OOD routes
- K228/K229 already shipped (`04cc25a`)

## Hard stops
- NEEDS VERIFICATION on author numbers / Wu figures
- META spot watch only (no options lotto); REA sentiment only (not XSP tradable)
- No auto-writes to watches.json; no order bots; no live calibrator
- GREEN playbook_snapshot gates unchanged
