"""FOMC decision-day calendar for paper/research gates.

2021-2026 dates from federalreserve.gov/monetarypolicy/fomccalendars.htm
(last day of each scheduled meeting). 2016-2020 from the Fed historical
calendars, including the 2020-03-03 and 2020-03-15 unscheduled meetings.

Never used to place live orders.
"""

from __future__ import annotations

from datetime import date, timedelta

FOMC_DECISION_DATES: frozenset[date] = frozenset(
    (
        date(2016, 1, 27),
        date(2016, 3, 16),
        date(2016, 4, 27),
        date(2016, 6, 15),
        date(2016, 7, 27),
        date(2016, 9, 21),
        date(2016, 11, 2),
        date(2016, 12, 14),
        date(2017, 2, 1),
        date(2017, 3, 15),
        date(2017, 5, 3),
        date(2017, 6, 14),
        date(2017, 7, 26),
        date(2017, 9, 20),
        date(2017, 11, 1),
        date(2017, 12, 13),
        date(2018, 1, 31),
        date(2018, 3, 21),
        date(2018, 5, 2),
        date(2018, 6, 13),
        date(2018, 8, 1),
        date(2018, 9, 26),
        date(2018, 11, 8),
        date(2018, 12, 19),
        date(2019, 1, 30),
        date(2019, 3, 20),
        date(2019, 5, 1),
        date(2019, 6, 19),
        date(2019, 7, 31),
        date(2019, 9, 18),
        date(2019, 10, 30),
        date(2019, 12, 11),
        date(2020, 1, 29),
        date(2020, 3, 3),
        date(2020, 3, 15),
        date(2020, 4, 29),
        date(2020, 6, 10),
        date(2020, 7, 29),
        date(2020, 9, 16),
        date(2020, 11, 5),
        date(2020, 12, 16),
        date(2021, 1, 27),
        date(2021, 3, 17),
        date(2021, 4, 28),
        date(2021, 6, 16),
        date(2021, 7, 28),
        date(2021, 9, 22),
        date(2021, 11, 3),
        date(2021, 12, 15),
        date(2022, 1, 26),
        date(2022, 3, 16),
        date(2022, 5, 4),
        date(2022, 6, 15),
        date(2022, 7, 27),
        date(2022, 9, 21),
        date(2022, 11, 2),
        date(2022, 12, 14),
        date(2023, 2, 1),
        date(2023, 3, 22),
        date(2023, 5, 3),
        date(2023, 6, 14),
        date(2023, 7, 26),
        date(2023, 9, 20),
        date(2023, 11, 1),
        date(2023, 12, 13),
        date(2024, 1, 31),
        date(2024, 3, 20),
        date(2024, 5, 1),
        date(2024, 6, 12),
        date(2024, 7, 31),
        date(2024, 9, 18),
        date(2024, 11, 7),
        date(2024, 12, 18),
        date(2025, 1, 29),
        date(2025, 3, 19),
        date(2025, 5, 7),
        date(2025, 6, 18),
        date(2025, 7, 30),
        date(2025, 9, 17),
        date(2025, 10, 29),
        date(2025, 12, 10),
        date(2026, 1, 28),
        date(2026, 3, 18),
        date(2026, 4, 29),
        date(2026, 6, 17),
        date(2026, 7, 29),
    )
)


def is_fomc_decision_day(d: date) -> bool:
    return d in FOMC_DECISION_DATES


def near_fomc(d: date, *, before: int = 2, after: int = 1) -> bool:
    """True if *d* is in [decision-before, decision+after] calendar days."""
    for decision in FOMC_DECISION_DATES:
        if decision - timedelta(days=before) <= d <= decision + timedelta(days=after):
            return True
    return False
