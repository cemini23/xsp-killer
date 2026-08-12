# Plan — prod briefs → XSP Killer (2026-08-12)

**Status:** IMPLEMENTED IN CURSOR (+ GPTSOL debug)
**Lane:** hard (log-only weather)

## CODE
- `xsp-k233-fed-speaks-vol-surface.md` + `xsp-k233-wublock-derivatives-volume.md` → single `k233:` weather block
- Overnight ends `keep_tight_vs_k232`
- Stack includes still-uncommitted K231/K232 from 2026-08-11

## Skip
- Harness K270–K273 / OOD routes
- Do **not** re-tune Lane A entry/sizing from ConvLSTM paper
- Do **not** flip HL perp exposure sizes from Wu derivatives snapshot

## Hard stops
- Both K233 briefs: no strategy code / timing-regime + venue-vol context only
- GREEN playbook_snapshot gates unchanged; no live calibrator
