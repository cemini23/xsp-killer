# Elite edge — SMB 20-DMA put credit, skip FOMC

**Live stays NO-GO.** This hunt used Cemini shared wiki research the first hunt did not.

## Next action

Paper-shadow this book only. Do not flip `LIVE_*`. Do not keep expanding long-call grids.

## Did the first hunt use Cemini shared research?

No. It used RH SPY daily + UW 15m only. It missed:

- `tipdrop-kit/projects/llm-wiki-by-cemini/wiki/concepts/xsp-put-credit-spread-small-account-smb.md` (K79 — 20-DMA, 14 DTE XSP put credit)
- `wiki/concepts/options-capital-velocity-credit-spreads-smb.md` (76% early close)
- `wiki/concepts/fomc-iv-surface-dynamics.md` + K155 FOMC calendar
- Official Fed decision days 2021–2026

## The edge

Sell a **14 DTE, 5-wide ATM put credit** when SPY is **above the 20-day MA**. Friday flatten. Take **76% of credit**. **Dark** FOMC T−2 through T+1.

| Split | ROC on max risk | n |
|---|---:|---:|
| Train | +13.1% | — |
| Val | +8.7% | — |
| Test | **+9.6%** | 244 |
| Full | +11.5% | 1,148 |
| Win | 73.4% | |
| $ / XSP contract | +$35.50 | |

Every calendar year 2016–2026 is green. Weakest: **2022 +3.0%**. **2025 +7.6%** (the hole in yesterday’s quiet-only book). 2020 +17.6% because the crash was below the 20-DMA.

Tighter variant (also add quiet volume): n=534, test **+10.8%**, 2025 +5.9%, still 11/11 years green.

## What the wiki got wrong

K233 “enter long calls before FOMC to harvest IV bid-up” produced **5 trades**. Not an edge. Use the calendar to **skip** selling, not to buy premium.

## Rejected

- 1-wide SMB print (+37% test, 92% win): bid-ask / $0.12 slip makes it unreal.
- Reclaim-only 20-DMA cross: coding bug, duplicate of “above MA”.
- FOMC crush T−1 only: +7.2% test but n_test=13.

## Honesty

Modeled BS with trailing 20d realized vol, not historical XSP fills. Return is **P&L / (width − credit)**, not return on credit. Still paper-only.

## Artifacts

`reports/backtest/elite_smb_20260816T074606Z.{md,json}`  
`scripts/research_elite_smb.py`
