"""NFP (first-Friday) calendar for research/paper gates.

First Friday of each month, with January holiday delays when the
formula lands on New Year's Day / the observed holiday week.

Never used to place live orders.
"""

from __future__ import annotations

from datetime import date, timedelta

# When the mechanical first Friday is a federal holiday week, BLS
# publishes the following Friday. January is the recurring case.
NFP_OVERRIDES: dict[date, date] = {
    date(2016, 1, 1): date(2016, 1, 8),
    date(2021, 1, 1): date(2021, 1, 8),
    date(2020, 1, 3): date(2020, 1, 10),
    date(2025, 1, 3): date(2025, 1, 10),
}


def first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def nfp_date(year: int, month: int) -> date:
    raw = first_friday(year, month)
    return NFP_OVERRIDES.get(raw, raw)


def nfp_fridays(start_year: int = 2016, end_year: int = 2026) -> frozenset[date]:
    out: set[date] = set()
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            out.add(nfp_date(year, month))
    return frozenset(out)


NFP_FRIDAYS: frozenset[date] = nfp_fridays()


def week_friday(d: date) -> date:
    return d + timedelta(days=(4 - d.weekday()))


def nfp_week(d: date) -> bool:
    """True Mon–Fri of an NFP week (decision Friday is NFP)."""
    return week_friday(d) in NFP_FRIDAYS
