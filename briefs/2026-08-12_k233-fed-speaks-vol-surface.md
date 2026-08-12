---
title: K233 — XSP — Fed Speaks: FOMC pre-announcement IV surface
type: brief
target: ceminiSuite
created: 2026-08-12
updated: 2026-08-12
---

## Target

CeminiSuite — XSP killer bot (Lane A long-call timing).

## Summary

arXiv 2608.10693 (Adamski & Ślepaczuk): IV builds before scheduled FOMC meetings, concentrated in **short-dated OTM** options and **amplified in high-vol regimes**. ConvLSTM forecasts the surface on announcement days but the edge over random walk is noise-bounded. Actionable: pre-FOMC short-dated IV bid-up is a timing edge for Lane A long-call entry, regime-dependent.

## Body

1. **Entry timing**: entering long calls *before* scheduled FOMC captures the pre-announcement IV elevation, not just the directional move. Add the FOMC calendar as a Lane A timing input.
2. **Regime interaction**: elevation is stronger in high-vol regimes — high-vol + approaching FOMC favors earlier entry / larger sizing; calm regime → normal entry rules.
3. **Modeling note**: IV-surface ML (ConvLSTM without PCA) works on abnormal days but is an enhancement to regime conditioning, not standalone alpha. Do not re-tune Lane on this paper's forecasts.
4. **No code** this brief — timing/regime input only.

## Sources

- @wiki/sources/arxiv-2608.10693-fed-speaks-vol-surface-2026-08-12.md
- @wiki/concepts/fomc-iv-surface-dynamics.md
- @wiki/concepts/xsp-lane-trading-framework.md
- @wiki/concepts/xsp-vol-regime-gates.md
