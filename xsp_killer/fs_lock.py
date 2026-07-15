"""Portable exclusive file locks.

Backend order:
1. ``portalocker`` (cross-platform, preferred)
2. ``fcntl`` (Unix)
3. ``msvcrt`` (Windows file-region lock)

Never silently no-ops when a locking backend is available. If no backend can
lock, logs loudly and raises ``RuntimeError`` so callers do not race unlocked.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import BinaryIO, TextIO, Any

logger = logging.getLogger("xsp_killer.fs_lock")

_BACKEND: str | None = None
_portalocker: Any = None
_fcntl: Any = None
_msvcrt: Any = None


def _init_backend() -> str:
    global _BACKEND, _portalocker, _fcntl, _msvcrt
    if _BACKEND is not None:
        return _BACKEND

    try:
        import portalocker as _pl

        _portalocker = _pl
        _BACKEND = "portalocker"
        return _BACKEND
    except ImportError:
        pass

    try:
        import fcntl as _fc

        _fcntl = _fc
        _BACKEND = "fcntl"
        return _BACKEND
    except ImportError:
        pass

    if sys.platform == "win32":
        try:
            import msvcrt as _ms

            _msvcrt = _ms
            _BACKEND = "msvcrt"
            return _BACKEND
        except ImportError:
            pass

    _BACKEND = "none"
    logger.error(
        "No file-lock backend available (tried portalocker, fcntl, msvcrt). "
        "Install portalocker: pip install portalocker"
    )
    return _BACKEND


def lock_backend() -> str:
    """Return the active lock backend name (for tests / diagnostics)."""
    return _init_backend()


def flock_ex(fh: BinaryIO | TextIO) -> None:
    """Acquire an exclusive lock on an open file handle. Blocks until held."""
    backend = _init_backend()
    if backend == "portalocker":
        # LOCK_EX blocks; fail_when_locked=False is the default blocking mode.
        _portalocker.lock(fh, _portalocker.LOCK_EX)
        return
    if backend == "fcntl":
        _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)
        return
    if backend == "msvcrt":
        # Lock a single byte from the start of the file (exclusive, blocking).
        # msvcrt.locking LK_LOCK retries ~10s then raises OSError.
        pos = fh.tell()
        fh.seek(0, 2)
        if fh.tell() == 0:
            # Empty files need ≥1 byte for a region lock.
            mode = getattr(fh, "mode", "r")
            fh.write(b"\0" if "b" in mode else " ")  # type: ignore[arg-type]
            fh.flush()
        fh.seek(0)
        _msvcrt.locking(fh.fileno(), _msvcrt.LK_LOCK, 1)
        fh.seek(pos)
        return
    raise RuntimeError(
        "file lock unavailable: no portalocker/fcntl/msvcrt backend "
        "(install portalocker for portable locks)"
    )


def flock_un(fh: BinaryIO | TextIO) -> None:
    """Release an exclusive lock acquired via :func:`flock_ex`."""
    backend = _init_backend()
    if backend == "portalocker":
        try:
            _portalocker.unlock(fh)
        except Exception as exc:  # noqa: BLE001 — best-effort unlock
            logger.warning("portalocker unlock failed: %s", exc)
        return
    if backend == "fcntl":
        try:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fcntl unlock failed: %s", exc)
        return
    if backend == "msvcrt":
        try:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("msvcrt unlock failed: %s", exc)
        return
    # No backend — flock_ex would have raised; unlock is a no-op with warning.
    logger.error("flock_un called with no lock backend")


def open_ex_lock(path: Path, *, mode: str = "a+") -> TextIO:
    """Open ``path`` and take an exclusive lock.

    Raises ``RuntimeError`` if no lock backend can lock the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open(mode, encoding="utf-8")
    try:
        flock_ex(fh)
    except Exception:
        fh.close()
        raise
    return fh
