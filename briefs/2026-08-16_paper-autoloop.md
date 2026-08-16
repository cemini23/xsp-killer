# Paper autoloop — no manual entry/monitor

**LIVE_* stay false.** The tick process forces them false even if `.env` says otherwise.

## Next action

Nothing. Tasks are registered on this Windows box. Heartbeat: `briefs/paper-autoloop-latest.json`.

## What runs by itself

Every 15 minutes + extra 15:45 / 15:50 / 15:55 ET Mon–Fri:

1. Lane A paper entry / monitor / intraday / variants
2. Lane PC 14 DTE (soaking sleeve)
3. Lane PC 7 DTE Mon/Tue (separate state)

Windows tasks: `XSP-Killer-PaperTick`, `XSP-Killer-PaperTick-EntryWindow`.
VPS: `deploy/systemd/xsp-killer-paper-tick.timer` (enable on next deploy).

Re-install: `powershell -ExecutionPolicy Bypass -File scripts\install_windows_paper_tasks.ps1`

## Honesty

Paper only. No multi-leg place. PC marks are still modeled rv20 until the chain is open.
