from __future__ import annotations

import pytest

from xsp_killer.backtest import report


def test_familywise_max_stat_detects_strong_variant_and_controls_nulls():
    sessions = [f"2026-01-{day:02d}" for day in range(1, 31)]
    family = {
        "strong": [(session, 0.2) for session in sessions],
        "null_a": [
            (session, 0.03 if i % 2 else -0.03)
            for i, session in enumerate(sessions)
        ],
        "null_b": [
            (session, -0.02 if i % 3 else 0.04)
            for i, session in enumerate(sessions)
        ],
    }
    result = report.familywise_max_stat_mcpt(family, n_perm=1000, seed=7)
    assert result["strong"]["familywise_pass_5pct"] is True
    assert result["null_a"]["familywise_pass_5pct"] is False
    assert result["null_b"]["familywise_pass_5pct"] is False


def test_familywise_max_stat_draws_one_shared_sign_per_session(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def deterministic_draw(session_keys, rng):
        keys = tuple(session_keys)
        calls.append(keys)
        return {key: (1.0 if i % 2 else -1.0) for i, key in enumerate(keys)}

    monkeypatch.setattr(report, "_draw_session_signs", deterministic_draw)
    family = {
        "a": [("d1", 0.1), ("d2", -0.2), ("d3", 0.3)],
        "b": [("d1", -0.4), ("d2", 0.5), ("d3", -0.6)],
    }
    report.familywise_max_stat_mcpt(family, n_perm=11, seed=1)
    assert calls == [("d1", "d2", "d3")] * 11


@pytest.mark.parametrize("n_perm", [0, -1])
def test_familywise_max_stat_rejects_nonpositive_permutations(n_perm):
    with pytest.raises(ValueError, match="n_perm"):
        report.familywise_max_stat_mcpt({"a": [("d1", 0.1)]}, n_perm=n_perm)


def test_familywise_max_stat_skips_invalid_observations_deterministically():
    family = {
        "a": [
            ("d1", 0.1),
            ("d2", None),
            (None, 0.2),
            ("d3", float("nan")),
            ("malformed",),
        ],
        "b": None,
        "c": 7,
    }
    first = report.familywise_max_stat_mcpt(family, n_perm=20, seed=3)
    second = report.familywise_max_stat_mcpt(family, n_perm=20, seed=3)
    assert first == second
    assert first["a"]["n_trades"] == 1
    assert first["b"]["n_trades"] == 0
    assert first["c"]["n_trades"] == 0
