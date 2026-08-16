from datetime import date

from xsp_killer.fomc_calendar import is_fomc_decision_day, near_fomc


def test_known_fed_decision_days():
    assert is_fomc_decision_day(date(2025, 3, 19))
    assert is_fomc_decision_day(date(2026, 1, 28))
    assert not is_fomc_decision_day(date(2026, 1, 27))


def test_near_fomc_blocks_tminus2_through_tplus1():
    decision = date(2026, 1, 28)
    assert near_fomc(date(2026, 1, 26), before=2, after=1)
    assert near_fomc(decision, before=2, after=1)
    assert near_fomc(date(2026, 1, 29), before=2, after=1)
    assert not near_fomc(date(2026, 1, 25), before=2, after=1)
    assert not near_fomc(date(2026, 1, 30), before=2, after=1)
