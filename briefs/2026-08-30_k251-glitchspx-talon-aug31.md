---
title: xsp-k251 — Glitch SPX Talon 31 Aug–4 Sep HITL map (SPXW OTE vs SPY/QQQ/IWM)
type: brief
tags: [brief, xsp, k251, talon]
target: ceminiSuite
created: 2026-08-30
updated: 2026-08-30
---

## Target

CeminiSuite — XSP killer / Lane A–B hedge context (informational). HITL only.

## Summary

Verdict: **awareness, no auto-arm.** Talon week of 31 Aug–4 Sep (sheet dated 30 Aug) still prints high bullish breadth (66/2, 97.0% score-weight) but the average snapshot move is **−0.92%** and the index dashboard is defensive. SPXW is an OTE watch (first-target R:R 0.1:1), not a chase. SPY, QQQ, and IWM are rally-fail maps. VXX remains a vol warning. SMH is constructive only around a lower floor. Effort: 10–15 min operator read; no code this brief.

## Body

1. Treat Talon as a **map**, not a Lane A buy list. Do not rewrite single-name screens from RIVN/DLO/BABA/RBLX/etc.
2. Size from the dashboard, not the 66-setup count or 97% score-weight:
   - SPXW $7,711.76 / OTE $7,650 / inv $7,623 / useful hold $7,725. Do not chase; first-target R:R is 0.1:1.
   - SPY: fail $770–$771 then accept below $769 → $765–$760. Reclaim $772 kills the bearish structure.
   - QQQ: fail $718–$720 then accept below $715 → $710–$705. Reclaim $720 improves growth risk budget.
   - IWM: fail $297–$298 then accept below $294. Reclaim $299 invalidates the bearish structure.
   - VXX: warn if it clears $19.50 while SPY or QQQ weaken. Loss of $17 weakens the vol warning.
   - SMH: hold $545–$540 or break-hold-retest $565. Accept below $535 weakens AI-beta.
3. Process: OTE/pullback first; break-hold-retest second; no trade if price is extended between entry and first target.
4. **No auto-arm** of `watches.json`. Operator must name symbol + op + level.
5. No code this brief.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Talon is a prototyping AI analyst (skylit.ai) | High | Map only; operator hypothesis before any Lane change |
| 97% bullish score-weight while SPY/QQQ/IWM are rally-fail | High | Let the dashboard cap size; do not chase breadth |
| Auto-rewrite of prod watches | High | HITL only |

## Phasing

- **Phase 1 (this brief):** operator read; optional HITL watch if a named level is armed later.
- Success: no auto-arm; wiki source remains the record.

## Sources

- @sources/substack-rss-glitchspx-2026-08-30-talon-weekly.md
- @concepts/xsp-lane-trading-framework.md
- @concepts/guruwatcher-macro-watches.md
