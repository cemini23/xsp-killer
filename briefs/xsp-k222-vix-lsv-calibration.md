---
title: xsp-k222 — VIX-first + amortizing LSV calibration awareness
type: brief
created: 2026-08-04
---

## Target
CeminiSuite / xsp-killer — cemini-prod

## Summary
Two vol-calibration papers for Lane B / index-options hedge research: **VDV** (VIX-first joint SPX–VIX) and **amortizing LSV neural operator** (98.5→0.6 ms synthetic latency). Awareness only — do not wire as live auto-calibrator.

## Body
1. arXiv 2608.01479 — calibrate VIX futures/options first; derive SPX SV consistent with VIX.
2. arXiv 2608.01217 — DeepONet/FNO projection-consistent LSV triple; offline amortize, online evaluate.
3. Macro Aug 4 SMH/tech chat is GuruWatcher-primary; xsp may note MAGS/Tech bounce regime only.

## Sources
- @concepts/vix-first-joint-spx-vix-calibration.md
- @sources/arxiv-2608.01479-vix-derived-volatility-model.md
- @sources/arxiv-2608.01217-lsv-calibration-neural-operator.md
- @concepts/xsp-lane-trading-framework.md
