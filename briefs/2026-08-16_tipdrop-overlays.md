# TipDrop overlays on XSP paper (log-only)

**LIVE_* stay false. Overlays never veto.**

## What shipped

1. **TipSeeker sqlite** — latest SPY/SPXW king / floor / ceiling / net GEX on each paper tick. No extra UW calls.
2. **UW / yfinance SPY put mids** — Lane PC live marks prefer real puts; fall back to modeled rv20.
3. **IV rank + market-tide** — attached to the heartbeat.
4. **`would_skip` log** — put_tide / neg_gex / king_below. Never vetoes. 23-day join did not promote a skip.

Heartbeat field: `overlays` in `briefs/paper-autoloop-latest.json`.
