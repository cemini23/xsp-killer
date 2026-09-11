---
title: xsp-k245 — Glitch SPX Talon 24–28 Aug HITL map (SPXW vs VXX/IWM)
type: brief
tags: [brief, xsp, k245, talon]
target: ceminiSuite
created: 2026-08-22
updated: 2026-08-22
---

## Target

CeminiSuite — XSP killer / Lane A–B hedge context (informational). HITL only.

## Summary

Verdict: **awareness, no auto-arm.** Talon week of 24–28 Aug (sheet dated 21 Aug) is a stronger bullish breadth print than last week (137/5, 96.2% score-weight, +0.95% avg snapshot) but the index/vol map is **not one-way**. SPXW constructive while $7,573.50 holds; VXX/VIX still have bullish vol structure; SMH is an OTE watch; IWM is a bearish rally-fail near $300. Effort: 10–15 min operator read; no code this brief.

## Body

1. Treat Talon as a **map**, not a Lane A buy list. Do not rewrite single-name screens from LI/MBLY/BE/MU/etc.
2. Size from the dashboard, not the 137-setup count:
   - SPXW $7,674 / inv $7,573.50 / swing 8,030–8,070.
   - VXX OTE $18.50; warn if it clears $19.50 while IWM or SMH weaken.
   - VIX: healthier while it fails $15.50; accept above opens $16–17.
   - SMH: wait $555–552.50 hold or $565 break-hold-retest; $550 invalidates AI-beta cluster.
   - IWM: fail $299 → $295–290; reclaim $302–304 kills the bearish structure.
3. Process: OTE/pullback first; break-hold-retest second; no trade if price is extended between entry and first target.
4. **No auto-arm** of `watches.json`. Operator must name symbol + op + level.
5. No code this brief.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Talon is a prototyping AI analyst (skylit.ai) | High | Map only; operator hypothesis before any Lane change |
| Breadth looks one-way while VXX/IWM contradict | High | Let the dashboard cap size |
| Auto-rewrite of prod watches | High | HITL only |

## Phasing

- **Phase 1 (this brief):** operator read; optional HITL watch if a named level is armed later.
- Success: no auto-arm; wiki source remains the record.

## Sources

- @sources/substack-rss-glitchspx-2026-08-22-talon-weekly.md
- @concepts/xsp-lane-trading-framework.md
- @concepts/guruwatcher-macro-watches.md
