"""Portable exclusive file locks (fcntl on Unix; best-effort on Windows)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO, TextIO

logger = logging.getLogger("xsp_killer.fs_lock")

try:
    import fcntl as _fcntl
except ImportError:  # Windows — no fcntl; single-process Task Scheduler is OK
    _fcntl = None  # type: ignore[assignment]


def flock_ex(fh: BinaryIO | TextIO) -> None:
    if _fcntl is None:
        return
    _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)


def flock_un(fh: BinaryIO | TextIO) -> None:
    if _fcntl is None:
        return
    _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)


def open_ex_lock(path: Path, *, mode: str = "a+") -> TextIO:
    """Open ``path`` and take an exclusive lock (no-op lock on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open(mode, encoding="utf-8")
    try:
        flock_ex(fh)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("file lock unavailable for %s: %s", path, exc)
    return fh
