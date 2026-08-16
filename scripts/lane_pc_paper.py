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

from xsp_killer.paper_autoloop import (  # noqa: E402
    SpySnapshot,
    fetch_spy_snapshot,
    run_pc_cycle,
)
from xsp_killer.put_credit_paper import (  # noqa: E402
    DEFAULT_LOG,
    DEFAULT_SCOREBOARD,
    DEFAULT_STATE,
    ET,
    PcRules,
    load_state,
    replay_pc_daily,
    save_state,
    write_scoreboard,
)


def _snapshot(args: argparse.Namespace) -> SpySnapshot:
    close = getattr(args, "close", None)
    ma20 = getattr(args, "ma20", None)
    if close is not None and ma20 is not None:
        return SpySnapshot(
            close=float(close),
            ma20=float(ma20),
            rv20=0.16,
            asof=datetime.now(ET).date().isoformat(),
            mark_value=getattr(args, "mark", None),
        )
    snap = fetch_spy_snapshot()
    if getattr(args, "mark", None) is not None:
        snap.mark_value = float(args.mark)
    return snap


def _cmd_entry(args: argparse.Namespace) -> int:
    rules = PcRules.from_yaml(Path(args.rules) if args.rules else None)
    state = load_state(Path(args.state) if args.state else DEFAULT_STATE)
    snap = _snapshot(args)
    row = run_pc_cycle(
        rules=rules,
        state=state,
        snapshot=snap,
        now_et=datetime.now(ET),
        log_path=Path(args.log) if args.log else DEFAULT_LOG,
    )
    save_state(state, Path(args.state) if args.state else DEFAULT_STATE)
    print(json.dumps(row, indent=2, default=str))
    return 0


def _cmd_monitor(args: argparse.Namespace) -> int:
    rules = PcRules.from_yaml(Path(args.rules) if getattr(args, "rules", None) else None)
    state = load_state(Path(args.state) if args.state else DEFAULT_STATE)
    snap = _snapshot(args)
    row = run_pc_cycle(
        rules=rules,
        state=state,
        snapshot=snap,
        now_et=datetime.now(ET),
        log_path=Path(args.log) if args.log else DEFAULT_LOG,
    )
    save_state(state, Path(args.state) if args.state else DEFAULT_STATE)
    print(json.dumps(row, indent=2, default=str))
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
    e.add_argument("--close", type=float, default=None)
    e.add_argument("--ma20", type=float, default=None)
    e.add_argument("--rules", default=None)
    e.add_argument("--state", default=None)
    e.add_argument("--log", default=None)
    e.set_defaults(func=_cmd_entry)

    m = sub.add_parser("monitor")
    m.add_argument("--close", type=float, default=None)
    m.add_argument("--ma20", type=float, default=None)
    m.add_argument("--mark", type=float, default=None)
    m.add_argument("--above-ma20", dest="above_ma20", type=int, default=None)
    m.add_argument("--rules", default=None)
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
