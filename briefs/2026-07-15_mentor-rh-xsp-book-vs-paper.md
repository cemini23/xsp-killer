# 2026-07-15 — Mentor live XSP book vs Lane A paper

**Source:** Friend / mentor Robinhood screenshot (operator share), ~2026-07-15 18:36 ET.  
**Goal:** Keep paper bot honest against how the strategy originator actually books.

## Mentor open XSP (RH display)

RH lists XSP strikes as **755 / 757** (= **7550 / 7570** in chain/OCC-style units our bot uses).

| Position | Qty | Expiry | Approx DTE (as of 7/15) | Day P&L (screenshot) | Sleeve fit |
|----------|-----|--------|-------------------------|----------------------|------------|
| XSP **755** call | 1 | **9/30** | ~77 | +$77 ITM | Closer to **Lane B** (long-dated core / swing hold), not 14–28 DTE overnight |
| XSP **757** call | 2 | **7/16** | **1** | +$52 ITM | Short-dated — **outside** Lane A `dte_min: 14` |

Also on screen (not XSP): OKLO/IONQ/IREN/XLK equity calls — mentor is multi-name; bot is XSP-only by design.

## Our paper (Hetzner `/opt/xsp-killer`, post `eeffa7f`)

| Position | Qty | Expiry | DTE | Note |
|----------|-----|--------|-----|------|
| XSP **7550** call | 1 | **2026-07-31** | ~16 | Baseline Lane A: close entry 7/14, mark MTM ~+$471 at last monitor |

Rules today: entry 15:45–16:00 ET, `dte_min: 14` / `dte_max: 60`, `dte_pick: min`, cheapest near-ATM; exits anytime XSP session open on TP/SL/BB.

## Alignment takeaways

1. **Strike family matches** — mentor 755 ≈ our 7550 paper (ATM-ish XSP vs SPX ~7550).
2. **He is not only running “overnight 14 DTE”** — the 9/30 lot is a longer hold; the 7/16 lot is a **1-DTE** expression we deliberately exclude from Lane A auto-entry.
3. **Sizing** — mentor 2× on the short 757 vs our paper 1× on Jul31; matches “2-lot operator-profile” notes in `lane_a_rules.yaml` better than baseline qty 1.
4. **Lane B gap** — 9/30 (~2.5 mo) is between Lane A max 60 DTE and Lane B LEAPS (>180). If mentor routinely uses **monthly–quarterly** XSP calls as “core,” we should either stretch Lane A `dte_max` / add a mid-tenor variant, or document a **Lane A⅔** sleeve — do not silently merge into overnight rules.
5. **Next check with mentor (optional ask):** Is 7/16 a discretionary scalp / lottery, or part of the teachable system? Is 9/30 the “real” swing book we should shadow more than 14 DTE min-pick?

## Do not

- Flip `LIVE_*` / RH place from this screenshot alone (audit-v9 still NO-GO live writes).
- Treat mentor’s equity names (OKLO/IONQ/…) as XSP bot scope.
