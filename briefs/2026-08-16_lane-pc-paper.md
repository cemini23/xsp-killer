# Lane PC paper sleeve + next contender

**LIVE_* stay false.** Isolated from Lane A long-call paper.

## Next action

Weekday 15:45 ET: `python scripts/lane_pc_paper.py entry --close <SPY> --ma20 <20DMA>`
Until then the local book is the 10y replay scoreboard.

## What is papered locally

New sleeve, not a Lane A variant:

- `config/lane_pc_rules.yaml`
- `scripts/lane_pc_paper.py` (`entry` / `monitor` / `replay` / `scoreboard`)
- State: `briefs/lane-pc-state.json` (gitignored)
- Scoreboard: `briefs/lane-pc-scoreboard.json` (gitignored)
- Log: `logs/lane_pc_paper.jsonl`

Rules: 14 DTE, 5-wide ATM put credit, SPY > 20-DMA, FOMC T−2..T+1 dark, 76% velocity, Friday flatten, **one contract, no overlap**.

Sunday 2026-08-16 entry: **skip weekend**. SPY 776.34 > MA20 756.20 — would have been a candidate on a non-Friday weekday. Last session was Friday 8/14 (also blocked).

## Local paper result (non-overlapping)

| Book | n | Win | Mean $ / XSP | ROC on max risk |
|---|---:|---:|---:|---:|
| 10y replay (one-at-a-time) | 378 | 67.7% | +$37.94 | +12.3% |
| 2026 YTD | 16 | 68.8% | +$45.17 | +16.4% |

Blocked: 529 below MA, 505 Friday, 316 FOMC. That is the filter working.

Overlapping daily entries in the research hunt (n=1,148) were research-only. Paper is the honest one-position book.

## New edge outside Lane A (contender hunt)

Pre-registered, same elite bar. Call-credit-below-MA **failed** (win 53.6%).

| Book | Test ROC | 2025 | Win | Note |
|---|---:|---:|---:|---|
| **7 DTE put credit, above MA, FOMC skip** | **+12.5%** | +9.5% | 72.3% | Beats 14 DTE test +9.6%. 2022 only +0.6% |
| Turn-of-month 14 DTE put credit | +12.0% | +13.2% | 75.2% | n=246. Same structure, calendar subset |
| Iron condor above MA | +4.4% | +4.3% | **90.7%** | Every year +3.4–4.8%. Stability, not max $ |
| 16-delta put credit | +7.8% | +5.9% | 79.2% | Higher win, lower ROC than ATM |
| Call credit below MA | +4.6% | +2.0% | 53.6% | **Not elite** |

The 7 DTE book is the next paper candidate. Not wired yet — 14 DTE is what is soaking.

## Honesty

Replay marks are modeled rv20, not RH XSP fills. Next weekday close window should attach real SPY put quotes when the chain is up. No multi-leg place.
