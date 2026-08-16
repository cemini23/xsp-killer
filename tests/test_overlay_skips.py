from xsp_killer.overlay_skips import evaluate_overlay_skips


def test_no_overlays_is_not_a_skip():
    out = evaluate_overlay_skips(None)
    assert out["would_skip"] is False
    assert out["reasons"] == []
    assert out["veto"] is False


def test_put_tide_and_neg_gex_and_king_below():
    overlays = {
        "market_tide": {"bias": "put"},
        "tipseeker": {
            "tickers": {
                "SPY": {
                    "spot": 776.34,
                    "king_strike": 770.0,
                    "total_gex": -1.0e9,
                }
            }
        },
    }
    out = evaluate_overlay_skips(overlays)
    assert out["would_skip"] is True
    assert out["reasons"] == ["put_tide", "neg_gex", "king_below"]
    assert out["veto"] is False


def test_call_tide_pos_gex_king_above_is_clear():
    overlays = {
        "market_tide": {"bias": "call"},
        "tipseeker": {
            "tickers": {
                "SPY": {
                    "spot": 776.34,
                    "king_strike": 780.0,
                    "total_gex": 1.0e9,
                }
            }
        },
    }
    out = evaluate_overlay_skips(overlays)
    assert out["would_skip"] is False
    assert out["reasons"] == []
