#!/usr/bin/env python3
"""Build XSP Killer super-audit pack (Cemini harvest + bot review).

Usage:
  python3 scripts/build_xsp_killer_super_audit_pack.py
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

XSP_ROOT = Path(__file__).resolve().parent.parent
CEMINI = Path("/opt/cemini")
PROMPT = XSP_ROOT / "prompts" / "xsp_killer_super_audit_v9.md"
DEFAULT_OUT = XSP_ROOT / "reports" / "gap-audit" / "pack-xsp-killer-v9"


def _read_tail(path: Path, max_chars: int = 12000) -> str:
    if not path.is_file():
        return f"(missing: {path})"
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n… truncated {len(text) - max_chars} chars …"


def _read_json_pretty(path: Path) -> str:
    if not path.is_file():
        return f"(missing: {path})"
    try:
        return json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2)
    except json.JSONDecodeError:
        return _read_tail(path, 8000)


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> str:
    try:
        return subprocess.check_output(
            cmd,
            cwd=cwd or XSP_ROOT,
            env=env,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        ).strip()
    except Exception as exc:
        return f"(command failed: {exc})"


def _copy_tree_excerpt(
    src_dir: Path, out_dir: Path, pattern: str, max_chars: int = 25000
) -> list[str]:
    names: list[str] = []
    if not src_dir.is_dir():
        return names
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(src_dir.glob(pattern)):
        if not src.is_file():
            continue
        rel = src.name
        dst = out_dir / rel
        dst.write_text(_read_tail(src, max_chars), encoding="utf-8")
        names.append(f"{out_dir.name}/{rel}")
    return names


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- XSP Killer core ---
    xsp_src = out / "xsp_killer_source"
    xsp_names = _copy_tree_excerpt(XSP_ROOT / "xsp_killer", xsp_src, "*.py", 50000)
    config_names = _copy_tree_excerpt(XSP_ROOT / "config", out / "config", "*", 8000)
    docs_names = _copy_tree_excerpt(XSP_ROOT / "docs", out / "docs", "*.md", 15000)
    systemd_names = _copy_tree_excerpt(
        XSP_ROOT / "deploy" / "systemd", out / "systemd", "*", 4000
    )
    test_names = _copy_tree_excerpt(XSP_ROOT / "tests", out / "tests", "*.py", 20000)

    pytest_out = _run_cmd(
        ["python3", "-m", "pytest", "tests/", "-q", "--tb=no"],
        cwd=XSP_ROOT,
        env={**dict(os.environ), "XSP_KILLER_TEST_ISOLATION": "1"},
        timeout=120,
    )

    artifacts: dict[str, str] = {
        "xsp_git_log.txt": _run_cmd(["git", "log", "--oneline", "-15"], cwd=XSP_ROOT)
        + "\n\n"
        + _run_cmd(["git", "rev-parse", "HEAD"], cwd=XSP_ROOT),
        "cemini_git_log.txt": _run_cmd(["git", "log", "--oneline", "-10"], cwd=CEMINI)
        if CEMINI.is_dir()
        else "(cemini missing)",
        "pytest_results.txt": pytest_out,
        "lane_a_rules.yaml": _read_tail(
            XSP_ROOT / "config" / "lane_a_rules.yaml", 8000
        ),
        "lane_b_rules.yaml": _read_tail(
            XSP_ROOT / "config" / "lane_b_rules.yaml", 8000
        ),
        "lane_a_entry_latest.json": _read_json_pretty(
            XSP_ROOT / "briefs" / "xsp-lane-a-entry-latest.json"
        ),
        "lane_a_paper_pnl_latest.json": _read_json_pretty(
            XSP_ROOT / "briefs" / "xsp-lane-a-paper-pnl-latest.json"
        ),
        "lane_b_scorecard_latest.json": _read_json_pretty(
            XSP_ROOT / "briefs" / "lane-b-scorecard-latest.json"
        ),
        "paper_log_lane_a.jsonl": _read_tail(
            XSP_ROOT / "logs" / "xsp_lane_a_paper.jsonl", 15000
        ),
        "paper_log_lane_b.jsonl": _read_tail(
            XSP_ROOT / "logs" / "xsp_lane_b_paper.jsonl", 8000
        ),
        "lane_a_variants.yaml": _read_tail(
            XSP_ROOT / "config" / "lane_a_variants.yaml", 12000
        ),
        "variants_scoreboard.json": _read_json_pretty(
            XSP_ROOT / "briefs" / "xsp-lane-a-variants-scoreboard.json"
        ),
        "entry_telemetry_latest.json": _read_json_pretty(
            XSP_ROOT / "briefs" / "xsp-lane-a-entry-telemetry-latest.json"
        ),
        "health_soak_latest.md": _read_tail(
            sorted((XSP_ROOT / "logs").glob("health_soak_*.md"))[-1]
            if list((XSP_ROOT / "logs").glob("health_soak_*.md"))
            else Path("(none)"),
            8000,
        ),
        "deployment_status.txt": _run_cmd(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            timeout=30,
        )
        + "\n\n"
        + _run_cmd(
            [
                "systemctl",
                "is-active",
                "xsp-killer-lane-a-entry.timer",
                "xsp-killer-lane-a-monitor.timer",
                "xsp-killer-lane-a-intraday.timer",
                "xsp-killer-lane-b-monitor.timer",
            ],
            timeout=15,
        ),
        "variant_log_yellow_mid_tail.jsonl": _read_tail(
            XSP_ROOT
            / "logs"
            / "xsp_lane_a_variant_v2_yellow_mid_bounce.jsonl",
            6000,
        ),
        "variant_log_yellow_top_tail.jsonl": _read_tail(
            XSP_ROOT
            / "logs"
            / "xsp_lane_a_variant_v2_yellow_top_quartile_bounce.jsonl",
            6000,
        ),
        "prior_audit_postpatch.md": _read_tail(
            XSP_ROOT
            / "briefs"
            / "2026-06-21_xsp-killer-super-audit-synthesis-v3-postpatch.md",
            12000,
        ),
        "variants_state.json": _read_json_pretty(
            XSP_ROOT / "briefs" / "xsp-lane-a-variants-state.json"
        ),
        "strategy_diagnosis.md": _read_tail(
            XSP_ROOT / "docs" / "lane-a-strategy-diagnosis.md", 8000
        ),
        "prior_audit_synthesis_v2.md": _read_tail(
            XSP_ROOT / "briefs" / "2026-06-16_xsp-killer-super-audit-synthesis-v2.md",
            15000,
        ),
        "prior_audit_synthesis_v8.md": _read_tail(
            XSP_ROOT / "briefs" / "2026-07-09_xsp-killer-super-audit-synthesis-v8.md",
            15000,
        ),
        "rh_mcp_connection_brief.md": _read_tail(
            XSP_ROOT
            / "briefs"
            / "2026-06-29_xsp-robinhood-agentic-mcp-connection-cemini-prod.md",
            16000,
        ),
        "rh_mcp.yaml": _read_tail(XSP_ROOT / "config" / "rh_mcp.yaml", 4000),
        "rh_mcp_runbook.md": _read_tail(XSP_ROOT / "docs" / "rh_mcp_runbook.md", 12000),
        "lane_a_monitor_latest.json": _read_json_pretty(
            XSP_ROOT / "briefs" / "xsp-lane-a-monitor-latest.json"
        ),
        "README.md": _read_tail(XSP_ROOT / "README.md", 8000),
        "env_example.txt": _read_tail(XSP_ROOT / ".env.example", 4000),
    }

    for name, body in artifacts.items():
        (out / name).write_text(body, encoding="utf-8")

    # --- Cemini steal candidates ---
    cemini_steal: dict[str, str] = {
        "macro_regime.py": _read_tail(
            CEMINI / "trading_playbook" / "macro_regime.py", 12000
        ),
        "vol_monitor.py": _read_tail(
            CEMINI / "options_greeks" / "vol_monitor.py", 10000
        ),
        "robinhood_adapter.py": _read_tail(
            CEMINI / "core" / "ems" / "adapters" / "robinhood.py", 15000
        ),
        "wiki_enforcement_gate.py": _read_tail(
            CEMINI / "core" / "wiki_enforcement_gate.py", 10000
        ),
        "orchestrator_wiki_context.py": _read_tail(
            CEMINI / "core" / "orchestrator_wiki_context.py", 10000
        ),
        "conductor_dispatch.py": _read_tail(CEMINI / "conductor" / "dispatch.py", 8000),
        "conductor_reviewer.py": _read_tail(
            CEMINI / "conductor" / "reviewer" / "reviewer.py", 10000
        ),
        "conductor_cycle_detector.py": _read_tail(
            CEMINI / "conductor" / "escalation" / "cycle_detector.py", 8000
        ),
        "xsp_lane_a_cemini_copy.py": _read_tail(
            CEMINI / "xsp_lane_a" / "lane_a_entry.py", 8000
        )
        if (CEMINI / "xsp_lane_a" / "lane_a_entry.py").is_file()
        else _read_tail(CEMINI / "scripts" / "xsp_lane_a_entry.py", 8000),
    }
    steal_dir = out / "cemini_steal_candidates"
    steal_dir.mkdir(parents=True, exist_ok=True)
    steal_names: list[str] = []
    for name, body in cemini_steal.items():
        (steal_dir / name).write_text(body, encoding="utf-8")
        steal_names.append(f"cemini_steal_candidates/{name}")

    # --- Briefs ---
    brief_dir = out / "cemini_briefs"
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_names: list[str] = []
    brief_candidates = [
        CEMINI
        / "briefs"
        / "archive"
        / "pivot-2026-06"
        / "xsp-cemini-superseded"
        / "2026-06-14_xsp-lane-a-overnight-swing-monitor-cemini-prod.md",
        CEMINI
        / "briefs"
        / "archive"
        / "pivot-2026-06"
        / "xsp-cemini-superseded"
        / "2026-06-14_xsp-lane-b-leaps-hedge-monitor-cemini-prod.md",
        CEMINI / "briefs" / "2026-05-29_k79-smb-capital-youtube-synthesis-cemini.md",
        CEMINI / "briefs" / "2026-06-09_cemini-suite-fable-super-audit-synthesis-v2.md",
        CEMINI
        / "briefs"
        / "2026-06-15_k117-regime-vol-gating-equity-signals-cemini-prod.md",
    ]
    for src in brief_candidates:
        if src.is_file():
            name = src.name
            (brief_dir / name).write_text(_read_tail(src, 20000), encoding="utf-8")
            brief_names.append(f"cemini_briefs/{name}")

    # --- OSINT wiki excerpts ---
    wiki_dir = out / "wiki_excerpts"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    wiki_files = {
        "spy.md": CEMINI / "research_wiki" / "entities" / "tickers" / "spy.md",
        "trading-playbook-research.md": CEMINI
        / "research_wiki"
        / "sources"
        / "trading-playbook-research.md",
        "greeks-4-3-29.md": CEMINI / "research_wiki" / "sources" / "greeks-4-3-29.md",
        "greeks-9-3-29.md": CEMINI / "research_wiki" / "sources" / "greeks-9-3-29.md",
        "kalshi-4-3-29.md": CEMINI / "research_wiki" / "sources" / "kalshi-4-3-29.md",
        "3-19-signal-fusion-engine-research.md": CEMINI
        / "research_wiki"
        / "sources"
        / "3-19-signal-fusion-engine-research.md",
    }
    xsp_wiki_root = XSP_ROOT / "research_wiki" / "concepts"
    if xsp_wiki_root.is_dir():
        for src in sorted(xsp_wiki_root.glob("xsp-*.md")):
            wiki_files[src.name] = src
    cemini_xsp = CEMINI / "research_wiki" / "concepts"
    if cemini_xsp.is_dir():
        for src in sorted(cemini_xsp.glob("xsp-*.md")):
            wiki_files.setdefault(src.name, src)
    wiki_names: list[str] = []
    for name, src in wiki_files.items():
        (wiki_dir / name).write_text(_read_tail(src, 12000), encoding="utf-8")
        wiki_names.append(f"wiki_excerpts/{name}")

    # Wiki XSP search summary
    wiki_search = _run_cmd(
        [
            "grep",
            "-ri",
            "-l",
            "-E",
            "xsp|mini.?spx|bollinger|vwap",
            str(CEMINI / "research_wiki"),
        ],
        timeout=30,
    )
    (out / "wiki_xsp_search_hits.txt").write_text(
        wiki_search or "(no hits)", encoding="utf-8"
    )

    # --- Prompt ---
    prompt_text = PROMPT.read_text(encoding="utf-8")
    index_lines = [
        f"# XSP Killer super-audit pack — built {ts}",
        "",
        f"XSP repo: `{XSP_ROOT}`",
        f"Cemini donor: `{CEMINI}`",
        "",
        "## XSP Killer source",
        "",
        *[f"- `{n}`" for n in xsp_names],
        "",
        "## Config / docs / systemd / tests",
        "",
        *[f"- `{n}`" for n in config_names + docs_names + systemd_names + test_names],
        "",
        "## Artifacts",
        "",
        *[f"- `{k}`" for k in artifacts],
        "",
        "## Cemini steal candidates",
        "",
        *[f"- `{n}`" for n in steal_names],
        "",
        "## Cemini briefs",
        "",
        *[f"- `{n}`" for n in brief_names],
        "",
        "## OSINT wiki excerpts",
        "",
        *[f"- `{n}`" for n in wiki_names],
        "- `wiki_xsp_search_hits.txt`",
        "",
        "## Prod notes",
        "",
        "- Librarian/OSINT remote wiki **destroyed**; local research_wiki only",
        "- XSP timers: xsp-killer-* on prod; cemini-xsp-lane-* disabled post-cutover",
        "- RH poll off by default; paper log only for Lane A entries",
        "- RH Agentic MCP scaffolded; agentic_account_id empty until David OAuth",
        "- **~12 active shadow keepers** (far-DTE OTM 45–60 pruned 2026-07-13)",
        "- Post-epoch only: pnl_epoch_at in scoreboard; promotion gate ≥20 sessions",
        "- Live fail-closed: LIVE_ENTRIES off; max_debit_usd + max_loss_usd gates",
        "",
    ]

    pack_index = "\n".join(index_lines)
    (out / "PACK_INDEX.md").write_text(pack_index, encoding="utf-8")

    # Slim prompt for cursor-audit + API: index + curated excerpts only
    key_excerpts = [
        out / "lane_a_rules.yaml",
        out / "lane_a_variants.yaml",
        out / "rh_mcp.yaml",
        out / "rh_mcp_runbook.md",
        out / "rh_mcp_connection_brief.md",
        out / "prior_audit_synthesis_v8.md",
        out / "variants_scoreboard.json",
        out / "deployment_status.txt",
        out / "entry_telemetry_latest.json",
        out / "prior_audit_postpatch.md",
        out / "xsp_killer_source" / "vol_monitor.py",
        out / "xsp_killer_source" / "data_hazards.py",
        out / "xsp_killer_source" / "health_soak.py",
        out / "strategy_diagnosis.md",
        out / "prior_audit_synthesis_v2.md",
        out / "xsp_killer_source" / "lane_a_entry.py",
        out / "xsp_killer_source" / "lane_a_monitor.py",
        out / "xsp_killer_source" / "lane_a_variants.py",
        out / "xsp_killer_source" / "lane_a_ta.py",
        out / "xsp_killer_source" / "macro_regime.py",
        out / "xsp_killer_source" / "paper_economics.py",
        out / "xsp_killer_source" / "robinhood_mcp.py",
        out / "xsp_killer_source" / "rh_broker.py",
        out / "docs" / "lane-a-brief.md",
        out / "paper_log_lane_a.jsonl",
        out / "pytest_results.txt",
        out / "xsp_git_log.txt",
    ]
    excerpt_parts = [pack_index, "\n---\n\n## Key excerpts\n"]
    for fp in key_excerpts:
        if fp.is_file():
            excerpt_parts.append(f"\n### {fp.relative_to(out)}\n")
            excerpt_parts.append(_read_tail(fp, 12000))
    audit_prompt = prompt_text.replace("{pack_index}", "\n".join(excerpt_parts))

    (out / "audit_prompt.md").write_text(audit_prompt, encoding="utf-8")
    print(f"Pack built → {out} ({len(audit_prompt)} chars prompt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
