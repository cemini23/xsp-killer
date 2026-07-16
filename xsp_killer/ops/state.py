"""Atomic JSON read/write + UTC timestamps (stdlib only)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("xsp_killer.ops.state")


def utc_now_iso() -> str:
    """UTC ISO-8601 with microsecond=0 (e.g. 2026-07-16T12:00:00+00:00)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    """Load JSON; return default on missing or corrupt file."""
    try:
        if not path.is_file():
            return default
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("read_json failed for %s: %s", path, exc)
        return default


def write_json(path: Path, data: Any) -> None:
    """Write JSON atomically (tmp in same dir + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=False, default=str) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
