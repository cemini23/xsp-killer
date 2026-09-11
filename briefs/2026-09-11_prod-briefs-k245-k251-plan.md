# Plan — prod briefs → XSP Killer (2026-09-11)

**Status:** READY FOR GROK
**Lane:** money (log-only weather / HITL awareness + VPS paper-tick deploy)

## CODE
- `xsp-k245-glitchspx-talon-aug24.md` → k245 weather (extends K240; overnight `keep_tight_vs_k240`)
- `xsp-k251-glitchspx-talon-aug31.md` → k251 weather (extends K245; overnight `keep_tight_vs_k245`)
- Enable `xsp-killer-paper-tick.timer` on this VPS (Aug 16 autoloop: "enable on next deploy")

## Already on origin (pulled)
- `3d2277c` paper-tick VBS hide + overnight NaN DMA guard + stale UW zero-mark reject
- 14 DTE soak + 7 DTE Mon/Tue paper sleeves in `paper_autoloop.py` (`config/lane_pc_7dte_rules.yaml`)
- K240 weather shipped `f0f913d`

## Skip (not this repo)
- Harness K282–K345 / Sept policy waves
- Guru-watcher K245 level wires (different repo)
- Aug 18 skip-plan items (CHIVE, ESTI, FastMCP, astronomy OOD)
- Inventing k252+ Talon weeks (no xsp brief after k251)
- LIVE_* / watches.json auto-arm / Lane A screen rewrite

## Hard stops
- Briefs: **HITL only** / **no auto-arm** of watches.json
- Talon = map not buy list; dashboard caps size; do not chase breadth
- Dashboard prices are context, not armed watch levels
- GREEN playbook_snapshot gates unchanged
- `LIVE_ENTRIES` / `LIVE_EXITS` stay false
