# Plan — prod briefs → XSP Killer (2026-08-18)

**Status:** SKIP — no implement
**Lane:** easy (triage only)

## CODE
- None. No new `xsp-*` brief on 2026-08-18.
- K240 GlitchSPX Talon HITL + Moontower RSSB shipped at `f0f913d` (overnight `keep_tight_vs_k236`).
- Latest xsp brief remains `/opt/cemini/briefs/xsp-k240-glitchspx-talon-rssb.md` (2026-08-17). Latest pm-k* is pm-k237 (2026-08-14).
- Do not invent k241 weather notes.

## Skip (not this repo)
- Harness K282 ARENA-audio, K283 JailbreakSkill — no clone into `.cursor/skills`
- Harness K285–K289 Mandato / VibeWorlding / ClawGym II / ESTI / HarnessEval-W — policy wires; Atto/cyber/game-dev dual interest
- K288 ESTI — cyber-primary; CCC same paper
- K290 CHIVE — runtime `wont_wire`
- OOD 2608.16795 astronomy backtesting — CCC
- prod-mcp FastMCP RBAC initialize `-32602` — `cemini_mcp`, not xsp-killer

## Hard stops
- **No code** / no YAML / Python / tests / systemd / LIVE_* edits
- `LIVE_ENTRIES` / `LIVE_EXITS` stay false
- No auto-arm of `watches.json`
- No Lane A screen rewrite
- No secrets in output
