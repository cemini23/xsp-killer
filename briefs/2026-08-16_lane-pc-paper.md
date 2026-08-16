# Lane PC paper sleeve + next contender

**LIVE_* stay false.** Isolated from Lane A long-call paper.

## Next action

Nothing. Autoloop is on. Each tick now logs TipSeeker king/floor/ceiling plus UW IV rank and market-tide (no veto). PC marks use UW/yfinance puts when the chain is up.

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

## New edge outside Lane A

**7 DTE Mon/Tue** is the upgrade. Friday flatten starves Wed/Thu 7 DTE of theta.

Honest one-position paper:

| Book | n | Win | Mean $ | ROC risk |
|---|---:|---:|---:|---:|
| 14 DTE Mon–Thu (this sleeve) | 378 | 67.7% | +$37.94 | +12.3% |
| 7 DTE Mon–Tue (replay only) | 325 | 67.7% | +$47.61 | +15.3% |

See `briefs/2026-08-16_deep-xsp-edge.md`. Dead: put debit below MA, pullback-only, 7/21 calendar.

## Honesty

Replay marks are modeled rv20, not RH XSP fills. Next weekday close window should attach real SPY put quotes when the chain is up. No multi-leg place.
