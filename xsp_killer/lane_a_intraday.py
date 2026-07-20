"""XSP Lane A intraday cycle — BB/VWAP entry in RTH; exits any XSP session."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from xsp_killer.lane_a_entry import (
    DEFAULT_RULES,
    DEFAULT_STATE,
    EntryRules,
    open_paper_positions,
    run_paper_entry,
)
from xsp_killer.lane_a_monitor import (
    DEFAULT_OUT,
    run_monitor,
    write_report,
    xsp_session_open,
)
from xsp_killer.lane_a_ta import TaRules, evaluate_ta_signals, in_rth

logger = logging.getLogger("xsp_killer.xsp_lane_a_intraday")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTRADAY_OUT = ROOT / "briefs" / "xsp-lane-a-intraday-latest.json"
ET = ZoneInfo("America/New_York")


@dataclass
class IntradayReport:
    evaluated_at: str
    in_rth: bool
    open_positions_n: int
    ta_signal: str
    entry_attempted: bool
    entry_entered: bool
    exit_alerts_n: int
    skip_reason: str | None = None
    ta_snapshot: dict[str, Any] | None = None
    monitor: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_intraday_cycle(
    *,
    rules_path: Path | None = None,
    state_path: Path | None = None,
    now_et: datetime | None = None,
    publish_intel: bool = True,
) -> IntradayReport:
    from xsp_killer.lane_a_monitor import load_state

    now = now_et or datetime.now(ET)
    evaluated_at = datetime.now(timezone.utc).isoformat()
    path = rules_path or DEFAULT_RULES
    ta_rules = TaRules.from_yaml(path)
    entry_rules = EntryRules.from_yaml(path)
    state = load_state(state_path or DEFAULT_STATE)
    open_n = len(open_paper_positions(state))
    max_open = max(1, int(entry_rules.max_open_positions or 1))

    report = IntradayReport(
        evaluated_at=evaluated_at,
        in_rth=in_rth(now),
        open_positions_n=open_n,
        ta_signal="none",
        entry_attempted=False,
        entry_entered=False,
        exit_alerts_n=0,
    )

    # Exits: any time XSP is tradeable (GTH/RTH/curb), regardless of clock windows.
    if open_n > 0 and xsp_session_open(now):
        ta_exit = None
        if report.in_rth:
            ta_exit = evaluate_ta_signals(ta_rules)
            report.ta_snapshot = ta_exit.to_dict()
            report.ta_signal = ta_exit.signal
        mon = run_monitor(
            rules_path=path,
            state_path=state_path,
            now_et=now,
            publish_intel=publish_intel,
            ta_signal=ta_exit,
            fetch_ta=False,
        )
        report.monitor = mon.to_dict()
        report.exit_alerts_n = len(mon.alerts)
        write_report(mon, DEFAULT_OUT)
        # If book is full, stop after exits. If room remains (max_open > open_n),
        # continue into entry evaluation below.
        if open_n >= max_open:
            _write_intraday_brief(report)
            return report
        # Reload state after monitor mutates paper exits.
        state = load_state(state_path or DEFAULT_STATE)
        open_n = len(open_paper_positions(state))
        report.open_positions_n = open_n
        if open_n >= max_open:
            _write_intraday_brief(report)
            return report

    if not report.in_rth:
        report.skip_reason = "outside RTH"
        _write_intraday_brief(report)
        return report

    ta = evaluate_ta_signals(ta_rules)
    report.ta_snapshot = ta.to_dict()
    report.ta_signal = ta.signal

    if not ta_rules.intraday_entry_enabled:
        report.skip_reason = "intraday entry disabled"
        _write_intraday_brief(report)
        return report

    if open_n >= max_open:
        report.skip_reason = f"max open positions ({max_open})"
        _write_intraday_brief(report)
        return report

    if not ta.entry_ok:
        report.skip_reason = f"no BB bounce: {ta.detail}"
        _write_intraday_brief(report)
        return report

    report.entry_attempted = True
    decision = run_paper_entry(
        rules_path=path,
        state_path=state_path,
        now_et=now,
        intraday=True,
        publish_intel=publish_intel,
        ta_signal=ta,
    )
    report.entry_entered = decision.entered
    report.skip_reason = decision.skip_reason
    if decision.errors:
        report.errors.extend(decision.errors)
    _write_intraday_brief(report)
    return report


def _write_intraday_brief(report: IntradayReport) -> Path:
    DEFAULT_INTRADAY_OUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_INTRADAY_OUT.write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return DEFAULT_INTRADAY_OUT
