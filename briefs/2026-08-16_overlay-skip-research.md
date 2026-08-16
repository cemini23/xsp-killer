# Overlay skip research — do not veto

**LIVE_* stay false. `would_skip` is log-only.**

## Next action

Nothing. Paper ticks now record `would_skip` reasons. No trade is blocked.

## 23-day join (TipDrop `uw_regime_shadow.jsonl`, 2026-07-15 → 2026-08-14)

Overlapping rv20 put-credit, same gates as the soaking book.

| Book | n | All ROC | Put-tide | Call-tide | If we skipped put-tide |
|---|---:|---:|---:|---:|---:|
| 14 DTE | 12 | +6.5% | +1.7% (n=7) | +13.2% (n=5) | +13.2% (n=5) |
| 7 DTE Mon/Tue | 5 | +24.0% | +35.5% (n=2) | +16.3% (n=3) | +16.3% (n=3) |

14 DTE looks worse on put-tide. 7 DTE looks **better** on put-tide. n is too small either way. **No skip is promoted.**

GEX / king-below: TipSeeker history is 5 rows from today. Not joinable.

## What is on

Each autoloop tick logs `would_skip.reasons` (`put_tide`, `neg_gex`, `king_below`) and `veto: false`. Revisit after ~60 session-days of that log.
