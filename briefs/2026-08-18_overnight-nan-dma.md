# Overnight NaN close looked like a DMA break

**LIVE_* stay false.**

At 12:04 AM ET 18 Aug, yfinance handed the autoloop a NaN SPY close. `NaN > 20-DMA` is false, so the open 7 DTE `pc-2026-08-17-775` paper put-credit was flattened on `dma_break`. Monday cash close was still 772.67 vs MA20 ~757 — not a DMA break.

Overnight SPY print around 12:34 AM ET: **770.35** (AH) vs RTH close **772.67** (−0.30%). Still ~13 pts above the 20-DMA.

Fix: drop non-finite daily bars; do not bump sessions or flip `above_ma20` without a finite close; session day follows bar `asof`, not midnight. Restored the 7 DTE paper position and tagged that close `void: overnight_nan_dma`.
