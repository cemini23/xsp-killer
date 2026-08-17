# 14 DTE fake velocity — stale UW $0 marks

**LIVE_* stay false.** Do not treat today’s two 14 DTE `velocity_76` closes as P&L.

## Next action

Nothing. Autoloop is still on. Next 14 DTE entry is tomorrow’s window at the earliest (one entry per calendar day). 7 DTE `pc-2026-08-17-775` stays open.

## What broke

UW printed a $0 debit to close while DTE was still 14. `put_credit_value` clamps that to 0, so velocity looked like 100% capture. Same-day re-entry did it twice. Closed rows had no `pnl_usd`.

## What shipped

- Reject live puts with non-positive mids, `net_credit <= 0`, or strike match farther than $1.
- Keep last good mark on a >40% jump or same-session implied velocity ≥ 76%.
- Do not `velocity_76` on a sub-$0.05 mark while DTE > 0.
- One paper entry per calendar day per sleeve.
- Real exits now write `pnl_usd` / `roc_risk`.
- Tagged the two 17 Aug 14 DTE closes `void: true` / `void_reason: stale_zero_mark`. Replay n=378 unchanged.

`would_skip` is still log-only. No overlay veto.
