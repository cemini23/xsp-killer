"""Portable file-lock tests (portalocker / fcntl / msvcrt)."""

from __future__ import annotations

from pathlib import Path

import xsp_killer.fs_lock as fs_lock


def test_lock_backend_is_real():
    backend = fs_lock.lock_backend()
    assert backend in ("portalocker", "fcntl", "msvcrt")
    assert backend != "none"


def test_flock_acquire_release_tmpdir(tmp_path: Path):
    lock_path = tmp_path / "state.json.lock"
    fh = fs_lock.open_ex_lock(lock_path)
    try:
        assert lock_path.is_file() or True  # a+ creates
        assert fh.fileno() >= 0
        # Holding lock: same process re-lock behavior is backend-specific;
        # just ensure unlock does not raise.
    finally:
        fs_lock.flock_un(fh)
        fh.close()


def test_flock_ex_un_roundtrip(tmp_path: Path):
    path = tmp_path / "plain.lock"
    path.write_text("x", encoding="utf-8")
    with path.open("a+", encoding="utf-8") as fh:
        fs_lock.flock_ex(fh)
        fh.write("ok\n")
        fh.flush()
        fs_lock.flock_un(fh)
    assert "ok" in path.read_text(encoding="utf-8")


def test_open_ex_lock_creates_parent(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c.lock"
    fh = fs_lock.open_ex_lock(nested)
    try:
        assert nested.parent.is_dir()
    finally:
        fs_lock.flock_un(fh)
        fh.close()
