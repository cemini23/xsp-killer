from datetime import date

from xsp_killer.nfp_calendar import first_friday, nfp_date, nfp_week, week_friday


def test_first_friday_august_2026() -> None:
    assert first_friday(2026, 8) == date(2026, 8, 7)


def test_january_2016_shifts_off_new_years() -> None:
    assert nfp_date(2016, 1) == date(2016, 1, 8)


def test_nfp_week_covers_monday_through_friday() -> None:
    assert nfp_week(date(2026, 8, 3))
    assert nfp_week(date(2026, 8, 7))
    assert not nfp_week(date(2026, 8, 10))


def test_week_friday() -> None:
    assert week_friday(date(2026, 8, 3)) == date(2026, 8, 7)
