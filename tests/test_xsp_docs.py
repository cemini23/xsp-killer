"""Tests for scripts/xsp_docs.py — K138 substrate projection CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "xsp_docs.py"

sys.path.insert(0, str(ROOT))
from scripts.xsp_docs import (  # noqa: E402
    check_invariants,
    extract_invariants,
    first_line_summary,
    has_invariants_line,
    module_bundle,
    parse_module_ast,
    symbol_bundle,
    top_level_symbols,
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_sample_module(tmp_path: Path) -> str:
    pkg = tmp_path / "inv_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sample.py").write_text(
        '''"""Sample module for invariant tests.

Invariants:
- entries must be idempotent
- state file is append-only
"""

class Widget:
    """Widget holds config."""

    def ping(self) -> str:
        """Return pong."""
        return "pong"


def greet(name: str) -> str:
    """Say hello to name."""
    return f"hello {name}"
''',
        encoding="utf-8",
    )
    return "inv_pkg.sample"


@pytest.fixture
def sample_module(tmp_path, monkeypatch):
    dotted = _write_sample_module(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    return dotted


def test_extract_invariants_and_summary():
    doc = "Headline summary.\n\nInvariants:\n- rule one\n- rule two"
    assert extract_invariants(doc) == "- rule one\n- rule two"
    assert first_line_summary(doc) == "Headline summary."
    assert has_invariants_line(doc) is True
    assert has_invariants_line("no block here") is False


def test_parse_top_level_symbols(sample_module):
    from scripts.xsp_docs import resolve_module_path

    path = resolve_module_path(sample_module)
    tree = parse_module_ast(path)
    symbols = top_level_symbols(tree)
    names = {s["name"]: s for s in symbols}
    assert names["Widget"]["kind"] == "class"
    assert names["Widget"]["summary"] == "Widget holds config."
    assert names["greet"]["kind"] == "function"
    assert names["greet"]["summary"] == "Say hello to name."


def test_module_bundle_on_xsp_killer_package():
    bundle = module_bundle("xsp_killer")
    assert bundle["module"] == "xsp_killer"
    assert "XSP Killer" in (bundle["docstring"] or "")
    assert bundle["invariants"] is None
    assert isinstance(bundle["symbols"], list)


def test_symbol_bundle_on_paper_economics():
    info = symbol_bundle("xsp_killer.paper_economics", "load_premium_scale")
    assert info["kind"] == "function"
    assert info["name"] == "load_premium_scale"
    assert info["lineno"] >= 1
    assert info["end_lineno"] >= info["lineno"]
    assert "premium scale" in (info["docstring"] or "").lower()


def test_symbol_bundle_on_sample_module(sample_module):
    info = symbol_bundle(sample_module, "Widget")
    assert info["name"] == "Widget"
    assert info["docstring"] == "Widget holds config."
    assert info["invariants"] is None


def test_check_invariants_pass_and_fail(sample_module, capsys):
    assert check_invariants([sample_module]) == 0
    out = capsys.readouterr().out
    assert f"ok {sample_module}" in out

    assert check_invariants(["xsp_killer"]) == 1
    err = capsys.readouterr().err
    assert "missing Invariants: xsp_killer" in err


def test_cli_module_json():
    proc = _run_cli("module", "xsp_killer.paper_economics")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["module"] == "xsp_killer.paper_economics"
    assert any(s["name"] == "PaperEconomics" for s in data["symbols"])


def test_cli_symbol_json():
    proc = _run_cli("symbol", "xsp_killer.paper_economics", "load_premium_scale")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["name"] == "load_premium_scale"
    assert "premium scale" in (data["docstring"] or "").lower()


def test_cli_check_invariants_exit_code(sample_module, tmp_path):
    import os

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "check-invariants", sample_module, "xsp_killer"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(tmp_path), str(ROOT)))},
    )
    assert proc.returncode == 1
    assert f"ok {sample_module}" in proc.stdout
    assert "missing Invariants: xsp_killer" in proc.stderr
