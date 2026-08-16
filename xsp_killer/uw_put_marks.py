"""SPY put mids for Lane PC paper marks. UW first, yfinance fallback.

1× scale (this book prices on SPY spot / XSP-like 5-wides). Fail-open to None
so the caller can use modeled rv20. Never places.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd


@dataclass
class PutCreditMarks:
    short_mid: float
    long_mid: float
    net_credit: float
    expiration: str
    source: str
    stale: bool = False


def _mid(row: pd.Series) -> float | None:
    bid = row.get("bid")
    ask = row.get("ask")
    last = row.get("lastPrice")
    try:
        b = float(bid) if bid is not None and pd.notna(bid) else None
        a = float(ask) if ask is not None and pd.notna(ask) else None
        last_f = float(last) if last is not None and pd.notna(last) else None
    except (TypeError, ValueError):
        return None
    if b is not None and a is not None and b > 0 and a > 0:
        return round((b + a) / 2.0, 4)
    if last_f is not None and last_f > 0:
        return round(last_f, 4)
    if a is not None and a > 0:
        return round(a, 4)
    if b is not None and b > 0:
        return round(b, 4)
    return None


def put_mid_from_chain(puts: pd.DataFrame, strike: float) -> float | None:
    if puts is None or puts.empty or "strike" not in puts.columns:
        return None
    idx = (puts["strike"].astype(float) - float(strike)).abs().idxmin()
    return _mid(puts.loc[idx])


def pick_expiry(*, dte: int, today: date, expirations: list[str]) -> str | None:
    if not expirations:
        return None
    target = today + timedelta(days=max(0, int(dte)))
    future = []
    for raw in expirations:
        try:
            exp = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if exp >= target:
            future.append(str(raw)[:10])
    if future:
        return sorted(future)[0]
    try:
        return max(str(x)[:10] for x in expirations)
    except ValueError:
        return None


def _marks_from_puts(
    puts: pd.DataFrame, short_k: float, long_k: float, expiration: str, source: str
) -> PutCreditMarks | None:
    short_mid = put_mid_from_chain(puts, short_k)
    long_mid = put_mid_from_chain(puts, long_k)
    if short_mid is None or long_mid is None:
        return None
    return PutCreditMarks(
        short_mid=short_mid,
        long_mid=long_mid,
        net_credit=round(short_mid - long_mid, 4),
        expiration=expiration,
        source=source,
        stale=False,
    )


def fetch_put_credit_marks(
    *,
    short_k: float,
    long_k: float,
    dte: int,
    today: date | None = None,
    provider: Any | None = None,
    yf_chain_fn: Callable[[str], Any] | None = None,
    yf_expirations: list[str] | None = None,
) -> PutCreditMarks | None:
    day = today or date.today()
    if provider is not None:
        try:
            exps = list(provider.list_expirations("SPY") or [])
            expiry = pick_expiry(dte=dte, today=day, expirations=exps)
            if expiry:
                chain = provider.get_options_chain("SPY", expiry)
                puts = getattr(chain, "puts", None) if chain is not None else None
                marks = _marks_from_puts(puts, short_k, long_k, expiry, "uw_spy_put")
                if marks is not None:
                    return marks
        except Exception:
            pass

    if yf_chain_fn is not None:
        try:
            exps = list(yf_expirations or [])
            expiry = pick_expiry(dte=dte, today=day, expirations=exps)
            if expiry:
                chain = yf_chain_fn(expiry)
                puts = getattr(chain, "puts", None) if chain is not None else None
                marks = _marks_from_puts(puts, short_k, long_k, expiry, "yfinance_spy_put")
                if marks is not None:
                    return marks
        except Exception:
            pass
    return None


def fetch_live_put_credit_marks(
    *,
    short_k: float,
    long_k: float,
    dte: int,
    today: date | None = None,
) -> PutCreditMarks | None:
    """Production helper. Fail-open. Uses TipDrop UW provider + yfinance cache."""
    provider = None
    try:
        from xsp_killer.uw_shadow import _get_provider

        provider = _get_provider()
    except Exception:
        provider = None

    def _yf(exp: str):
        from datetime import date as date_cls

        from xsp_killer.chain_cache import get_spy_option_chain

        return get_spy_option_chain(date_cls.fromisoformat(exp[:10]))

    yf_exps: list[str] = []
    try:
        from xsp_killer.chain_cache import get_spy_expirations

        yf_exps = list(get_spy_expirations() or [])
    except Exception:
        yf_exps = []

    return fetch_put_credit_marks(
        short_k=short_k,
        long_k=long_k,
        dte=dte,
        today=today,
        provider=provider,
        yf_chain_fn=_yf,
        yf_expirations=yf_exps,
    )
