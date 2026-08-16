#!/usr/bin/env python3
"""Local paper sleeve for the SMB 20-DMA put-credit book.

Commands:
  entry     evaluate today's close-window gates (log-only)
  monitor   mark/exit any open paper put-credit
  scoreboard print + write briefs/lane-pc-scoreboard.json
  replay    seed/refresh the local book from RH daily JSON

Never flips LIVE_ENTRIES / LIVE_EXITS. Never places multi-leg.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from xsp_killer.put_credit_paper import (  # noqa: E402
    DEFAULT_LOG,
    DEFAULT_SCOREBOARD,
    DEFAULT_STATE,
    ET,
    PcRules,
    append_log,
    evaluate_pc_exits,
    evaluate_pc_gates,
    load_state,
    replay_pc_daily,
    save_state,
    write_scoreboard,
)


def _cmd_entry(args: argparse.Namespace) -> int:
    rules = PcRules.from_yaml()
    now = datetime.now(ET)
    # Live quote path is best-effort; on weekends/close we still log the gate.
    close = args.close
    ma20 = args.ma20
    gate = evaluate_pc_gates(now_et=now, close=close, ma20=ma20, rules=rules)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "pc_entry" if gate.allowed else "pc_entry_skip",
        "allowed": gate.allowed,
        "reason": gate.reason,
        "close": close,
        "ma20": ma20,
        "logic_version": "xsp_lane_pc_smb_v1",
        "live_untouched": True,
    }
    append_log(row, Path(args.log) if args.log else DEFAULT_LOG)
    print(json.dumps(row, indent=2))
    return 0 if gate.allowed or gate.reason in (
        "weekend",
        "friday_no_entry",
        "weekday_blocked",
        "out_of_window",
        "fomc_window",
        "below_ma20",
        "ma20_unavailable",
    ) else 1


def _cmd_monitor(args: argparse.Namespace) -> int:
    rules = PcRules.from_yaml()
    state = load_state(Path(args.state) if args.state else DEFAULT_STATE)
    now = datetime.now(ET)
    open_pos = state.get("paper_positions") or {}
    if not open_pos:
        print(json.dumps({"open": 0, "event": "pc_monitor_idle"}))
        return 0
    closed = state.setdefault("closed", [])
    still = {}
    for pid, pos in open_pos.items():
        pos = dict(pos)
        if args.mark is not None:
            pos["mark_value"] = float(args.mark)
        if args.above_ma20 is not None:
            pos["above_ma20"] = bool(args.above_ma20)
        held = int(pos.get("sessions_held") or 0)
        reason = evaluate_pc_exits(pos, now_et=now, sessions_held=held, rules=rules)
        if reason:
            pos["status"] = "closed"
            pos["exit_reason"] = reason
            pos["exit_ts"] = datetime.now(timezone.utc).isoformat()
            closed.append(pos)
            append_log(
                {"event": "pc_exit", "position": pos, "reason": reason},
                Path(args.log) if args.log else DEFAULT_LOG,
            )
        else:
            still[pid] = pos
    state["paper_positions"] = still
    save_state(state, Path(args.state) if args.state else DEFAULT_STATE)
    print(json.dumps({"open": len(still), "closed_now": len(open_pos) - len(still)}))
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    from research_edge_hunt import load_rh_daily

    df = load_rh_daily(Path(args.bars))
    if args.since:
        since = datetime.fromisoformat(args.since).date()
        df = df[df["date"] >= since].reset_index(drop=True)
    rules = PcRules.from_yaml(Path(args.rules) if args.rules else None)
    rules.require_window = False
    if args.dte is not None:
        rules.dte = int(args.dte)
    if args.weekdays:
        rules.entry_weekdays = tuple(int(x) for x in args.weekdays.split(","))
    result = replay_pc_daily(df, rules)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["source_bars"] = str(args.bars)
    result["n_bars"] = int(len(df))
    out = Path(args.out) if args.out else DEFAULT_SCOREBOARD
    write_scoreboard(result, out)
    state = {
        "paper_positions": {},
        "closed": result["trades"],
        "replay": True,
        "generated_at": result["generated_at"],
    }
    save_state(state, Path(args.state) if args.state else DEFAULT_STATE)
    print(
        f"replay n={result['n_entries']} win={result['win_pct']} "
        f"mean$={result['mean_pnl_usd']} roc_risk={result['mean_roc_risk']}"
    )
    print(f"wrote {out}")
    return 0


def _cmd_scoreboard(args: argparse.Namespace) -> int:
    path = Path(args.scoreboard) if args.scoreboard else DEFAULT_SCOREBOARD
    if not path.is_file():
        print("no scoreboard yet — run replay first")
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps({k: payload[k] for k in payload if k != "trades"}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lane PC paper sleeve (log-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("entry")
    e.add_argument("--close", type=float, required=True)
    e.add_argument("--ma20", type=float, default=None)
    e.add_argument("--log", default=None)
    e.set_defaults(func=_cmd_entry)

    m = sub.add_parser("monitor")
    m.add_argument("--mark", type=float, default=None)
    m.add_argument("--above-ma20", dest="above_ma20", type=int, default=None)
    m.add_argument("--state", default=None)
    m.add_argument("--log", default=None)
    m.set_defaults(func=_cmd_monitor)

    r = sub.add_parser("replay")
    r.add_argument("--bars", required=True)
    r.add_argument("--since", default=None)
    r.add_argument("--out", default=None)
    r.add_argument("--state", default=None)
    r.add_argument("--dte", type=int, default=None)
    r.add_argument("--weekdays", default=None, help="comma weekdays 0=Mon")
    r.add_argument("--rules", default=None)
    r.set_defaults(func=_cmd_replay)

    s = sub.add_parser("scoreboard")
    s.add_argument("--scoreboard", default=None)
    s.set_defaults(func=_cmd_scoreboard)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
