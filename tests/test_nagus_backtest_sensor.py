"""Offline tests for Nagus backtest sensor (ops control plane)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from xsp_killer.ops.brain import PULL_LOG_MAX, load_brain
from xsp_killer.ops.emit import emit_from_report, make_slug
from xsp_killer.ops.paths import (
    ensure_layout,
    posts_path,
    resolve_ops_root,
)
from xsp_killer.ops.queue import count_jobs, find_job
from xsp_killer.ops.rules import classify_variant
from xsp_killer.ops.state import read_json

ROOT = Path(__file__).resolve().parents[1]


def _row(
    variant_id: str,
    *,
    n_trades: int = 40,
    mean: float = 0.01,
    win_pct: float = 55.0,
    median: float = 0.008,
    total: float = 100.0,
    mcpt_p: float | None = None,
    mcpt_pass: bool | None = None,
) -> dict[str, Any]:
    r: dict[str, Any] = {
        "variant_id": variant_id,
        "n_trades": n_trades,
        "win_pct": win_pct,
        "mean_net_pnl_pct": mean,
        "median_net_pnl_pct": median,
        "total_pnl_usd": total,
    }
    if mcpt_pass is not None or mcpt_p is not None:
        r["mcpt_p"] = mcpt_p
        r["mcpt_pass_5pct"] = mcpt_pass
    return r


def _payload(rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    ranked = sorted(rows, key=lambda r: r.get("mean_net_pnl_pct", 0.0), reverse=True)
    p: dict[str, Any] = {
        "generated_at": "2026-07-16T12:00:00+00:00",
        "mode": "fixture",
        "source": "fixture",
        "n_variants": len(ranked),
        "ranking": ranked,
        "healthy_windows": [],
        "meta": {},
    }
    p.update(extra)
    return p


@pytest.fixture
def ops_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ops"
    monkeypatch.setenv("XSP_OPS_ROOT", str(root))
    ensure_layout(root)
    return root


def test_emit_creates_layout(ops_root: Path) -> None:
    payload = _payload(
        [
            _row("v_alpha", mean=0.02, n_trades=40),
            _row("v_beta", mean=0.001, n_trades=5),
        ]
    )
    report = ops_root.parent / "lane_a_bt_20260716T120000Z.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    summary = emit_from_report(
        payload,
        report_json=report,
        report_md=report.with_suffix(".md"),
        root=ops_root,
        dry_run=False,
    )

    assert (ops_root / "state" / "brain.json").is_file()
    assert (ops_root / "queue" / "pending").is_dir()
    assert (ops_root / "packets").is_dir()
    assert summary["n_variants"] == 2
    brain = load_brain(ops_root)
    assert len(brain["pull_log"]) == 1
    assert brain["pull_log"][0]["sensor"] == "backtest_lane_a"


def test_mcpt_pass_emits_packet(ops_root: Path) -> None:
    payload = _payload(
        [
            _row("sweep_dte_1", mean=0.0123, n_trades=42, mcpt_p=0.032, mcpt_pass=True),
            _row("noise_v", mean=-0.01, n_trades=10),
        ]
    )
    report = ops_root.parent / "lane_a_bt_20260716T120000Z.json"
    report.write_text("{}", encoding="utf-8")

    summary = emit_from_report(payload, report_json=report, root=ops_root)

    slug = make_slug("20260716T120000Z", "sweep_dte_1")
    post = read_json(posts_path(slug, ops_root), {})
    assert post["action"] == "packet"
    assert post["status"] == "healthy"
    assert post["priority"] == "high"
    assert find_job(slug, ops_root) is not None
    status, job = find_job(slug, ops_root)  # type: ignore[misc]
    assert status == "pending"
    assert job["variant_id"] == "sweep_dte_1"

    pkts = list((ops_root / "packets").glob("*.md"))
    assert len(pkts) == 1
    text = pkts[0].read_text(encoding="utf-8")
    assert "sweep_dte_1" in text
    assert summary["n_mcpt_pass"] == 1
    assert len(summary["packets_written"]) == 1


def test_mcpt_fail_skipped(ops_root: Path) -> None:
    payload = _payload(
        [
            _row("bad_mcpt", mean=0.05, n_trades=100, mcpt_p=0.4, mcpt_pass=False),
        ]
    )
    summary = emit_from_report(
        payload,
        report_json="reports/backtest/lane_a_bt_test.json",
        root=ops_root,
    )
    assert summary["n_candidates"] == 0
    assert list((ops_root / "state" / "posts").glob("*.json")) == []
    assert count_jobs("pending", ops_root) == 0
    assert list((ops_root / "packets").glob("*.md")) == []


def test_topk_mean_candidate(ops_root: Path) -> None:
    # MCPT not run; rank 1; mean and trades above defaults
    payload = _payload(
        [
            _row("top_mean", mean=0.01, n_trades=30),
            _row("other", mean=0.005, n_trades=30),
        ]
    )
    clf = classify_variant(payload["ranking"][0], rank=1)
    assert clf["action"] == "packet"
    assert clf["status"] == "candidate"
    assert clf["priority"] == "med"

    summary = emit_from_report(
        payload,
        report_json="reports/backtest/lane_a_bt_topk.json",
        root=ops_root,
    )
    assert summary["n_candidates"] >= 1
    posts = list((ops_root / "state" / "posts").glob("*.json"))
    assert any("top_mean" in p.name for p in posts)
    assert list((ops_root / "packets").glob("*.md"))


def test_low_trades_watch_or_skip(ops_root: Path) -> None:
    # Positive mean but n_trades < MIN_TRADES (20) → not packet
    payload = _payload(
        [
            _row("thin", mean=0.02, n_trades=5),
        ]
    )
    clf = classify_variant(payload["ranking"][0], rank=1)
    assert clf["action"] != "packet"

    summary = emit_from_report(
        payload,
        report_json="reports/backtest/lane_a_bt_thin.json",
        root=ops_root,
    )
    assert list((ops_root / "packets").glob("*.md")) == []
    # either watch (if somehow enough) or skip — never packet
    for c in summary.get("candidates") or []:
        assert c["action"] != "packet"


def test_idempotent_reemit(ops_root: Path) -> None:
    payload = _payload(
        [
            _row("keep_me", mean=0.015, n_trades=50, mcpt_p=0.01, mcpt_pass=True),
        ]
    )
    report = "reports/backtest/lane_a_bt_idem.json"
    s1 = emit_from_report(payload, report_json=report, root=ops_root)
    s2 = emit_from_report(payload, report_json=report, root=ops_root)

    assert len(s1["jobs_enqueued"]) == 1
    assert len(s2["jobs_enqueued"]) == 0
    assert s2["jobs_skipped_existing"]
    assert len(list((ops_root / "queue" / "pending").glob("*.json"))) == 1
    assert len(list((ops_root / "packets").glob("*.md"))) == 1
    assert s2["packets_skipped_existing"]


def test_pull_log_appended_and_capped(ops_root: Path) -> None:
    payload = _payload([_row("v1", mean=0.01, n_trades=40)])
    for i in range(PULL_LOG_MAX + 5):
        emit_from_report(
            payload,
            report_json=f"reports/backtest/lane_a_bt_run{i}.json",
            root=ops_root,
        )
    brain = load_brain(ops_root)
    assert len(brain["pull_log"]) == PULL_LOG_MAX


def test_dry_run_no_writes(ops_root: Path, tmp_path: Path) -> None:
    # Fresh empty root — dry_run must not create durable artifacts
    empty = tmp_path / "empty_ops"
    payload = _payload(
        [
            _row("dry_v", mean=0.02, n_trades=40, mcpt_pass=True, mcpt_p=0.01),
        ]
    )
    summary = emit_from_report(
        payload,
        report_json="reports/backtest/lane_a_bt_dry.json",
        root=empty,
        dry_run=True,
    )
    assert summary["dry_run"] is True
    assert summary["n_candidates"] >= 1
    assert not empty.exists() or not list(empty.rglob("*"))
    # default ops_root fixture also untouched for this path
    assert list((ops_root / "state" / "posts").glob("*.json")) == []


def test_fail_open_in_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI still exits 0 and writes report if emit raises."""
    # Unit-test the try/except wrapper by invoking main with monkeypatched emit
    import scripts.backtest_lane_a as cli

    out_dir = tmp_path / "reports"
    out_dir.mkdir()

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated nagus failure")

    monkeypatch.setattr(
        "xsp_killer.ops.emit.emit_from_report",
        boom,
        raising=False,
    )
    # Import path used inside main after flag check
    import xsp_killer.ops.emit as emit_mod

    monkeypatch.setattr(emit_mod, "emit_from_report", boom)

    rc = cli.main(
        [
            "--mode",
            "fixture",
            "--no-baseline",
            "--variants",
            "v2_baseline_prod",
            "--out",
            str(out_dir),
            "--nagus",
        ]
    )
    assert rc == 0
    written = list(out_dir.glob("lane_a_bt_*.json"))
    assert written, "report must still be written on nagus failure"


def test_from_latest_picks_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    older = out_dir / "lane_a_bt_20260716T100000Z.json"
    newer = out_dir / "lane_a_bt_20260716T120000Z.json"
    older.write_text(
        json.dumps(_payload([_row("old_v", mean=0.01, n_trades=40)])),
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps(
            _payload(
                [
                    _row(
                        "new_v",
                        mean=0.02,
                        n_trades=40,
                        mcpt_pass=True,
                        mcpt_p=0.02,
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    # Ensure mtime order (newer is newer)
    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))

    from scripts.nagus_backtest_sensor import (  # noqa: I001
        find_latest_report,
        main as sensor_main,
    )

    assert find_latest_report(out_dir) == newer

    ops = tmp_path / "ops"
    monkeypatch.setenv("XSP_OPS_ROOT", str(ops))
    rc = sensor_main(
        ["--from-latest", "--out-dir", str(out_dir), "--ops-root", str(ops)]
    )
    assert rc == 0
    posts = list((ops / "state" / "posts").glob("*.json"))
    assert posts
    assert any("new_v" in p.name for p in posts)


def test_no_briefs_write(
    ops_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point a fake repo-ish tree; ensure emit never writes briefs/ or wiki/
    fake_repo = tmp_path / "repo"
    briefs = fake_repo / "briefs"
    wiki = fake_repo / "wiki"
    briefs.mkdir(parents=True)
    wiki.mkdir(parents=True)
    before_briefs = set(briefs.rglob("*"))
    before_wiki = set(wiki.rglob("*"))

    payload = _payload(
        [
            _row("pkt_v", mean=0.03, n_trades=50, mcpt_pass=True, mcpt_p=0.01),
        ]
    )
    emit_from_report(
        payload,
        report_json=str(fake_repo / "reports" / "backtest" / "lane_a_bt_x.json"),
        root=ops_root,
    )
    assert set(briefs.rglob("*")) == before_briefs
    assert set(wiki.rglob("*")) == before_wiki
    # packets only under ops root
    assert list((ops_root / "packets").glob("*.md"))
    assert not list(briefs.glob("*.md"))


def test_resolve_ops_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom_ops"
    monkeypatch.setenv("XSP_OPS_ROOT", str(custom))
    assert resolve_ops_root() == custom
    assert resolve_ops_root(tmp_path / "explicit") == tmp_path / "explicit"


def test_classify_rules_table() -> None:
    assert classify_variant(
        _row("h", mcpt_pass=True, mcpt_p=0.01, mean=0.01), rank=1
    )["status"] == "healthy"
    assert classify_variant(
        _row("n", mcpt_pass=False, mean=0.05, n_trades=100), rank=1
    )["action"] == "skip"
    assert classify_variant(
        _row("c", mean=0.01, n_trades=30), rank=1
    )["status"] == "candidate"
    assert classify_variant(
        _row("w", mean=0.01, n_trades=30), rank=10
    )["action"] == "watch"
    assert classify_variant(
        _row("s", mean=-0.01, n_trades=5), rank=1
    )["action"] == "skip"
