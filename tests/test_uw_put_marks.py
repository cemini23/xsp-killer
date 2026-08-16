from datetime import date
from types import SimpleNamespace

import pandas as pd

from xsp_killer.uw_put_marks import (
    fetch_put_credit_marks,
    pick_expiry,
    put_mid_from_chain,
)


def test_pick_expiry_first_on_or_after_target():
    exps = ["2026-08-17", "2026-08-21", "2026-08-28"]
    assert pick_expiry(dte=4, today=date(2026, 8, 17), expirations=exps) == "2026-08-21"
    assert pick_expiry(dte=7, today=date(2026, 8, 17), expirations=exps) == "2026-08-28"


def test_put_mid_nearest_strike():
    puts = pd.DataFrame(
        {
            "strike": [770.0, 775.0, 780.0],
            "bid": [4.0, 2.0, 1.0],
            "ask": [4.2, 2.2, 1.2],
            "lastPrice": [4.1, 2.1, 1.1],
        }
    )
    assert put_mid_from_chain(puts, 775.0) == 2.1
    assert put_mid_from_chain(puts, 776.0) == 2.1


class _Chain:
    def __init__(self, puts):
        self.puts = puts


class _Provider:
    def list_expirations(self, ticker: str):
        return ["2026-08-21", "2026-08-28"]

    def get_options_chain(self, ticker: str, expiry: str, spot_override=None):
        puts = pd.DataFrame(
            {
                "strike": [770.0, 775.0],
                "bid": [1.9, 3.8],
                "ask": [2.1, 4.2],
                "lastPrice": [2.0, 4.0],
            }
        )
        return _Chain(puts)


def test_fetch_put_credit_marks_from_uw():
    marks = fetch_put_credit_marks(
        short_k=775.0,
        long_k=770.0,
        dte=7,
        today=date(2026, 8, 17),
        provider=_Provider(),
        yf_chain_fn=lambda exp: None,
    )
    assert marks is not None
    assert marks.source == "uw_spy_put"
    assert marks.short_mid == 4.0
    assert marks.long_mid == 2.0
    assert marks.net_credit == 2.0


def test_fetch_put_credit_marks_falls_back_to_none():
    empty = SimpleNamespace(
        list_expirations=lambda t: [],
        get_options_chain=lambda *a, **k: None,
    )
    assert (
        fetch_put_credit_marks(
            short_k=775.0,
            long_k=770.0,
            dte=7,
            today=date(2026, 8, 17),
            provider=empty,
            yf_chain_fn=lambda exp: None,
        )
        is None
    )
