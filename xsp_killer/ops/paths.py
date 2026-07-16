"""Filesystem layout for the XSP Nagus ops control plane.

State root: ``$XSP_OPS_ROOT`` or ``.local/ops/xsp/``
  - state/brain.json
  - state/posts/<slug>.json
  - queue/{pending,running,done,failed}/
  - packets/
  - events/
"""

from __future__ import annotations

import os
from pathlib import Path

# xsp_killer/ops/paths.py → xsp_killer → repo root
PACKAGE_DIR = Path(__file__).resolve().parent
PKG_ROOT = PACKAGE_DIR.parent
REPO_ROOT = PKG_ROOT.parent

_OPS_OVERRIDE = os.environ.get("XSP_OPS_ROOT")
OPS_ROOT = (
    Path(_OPS_OVERRIDE)
    if _OPS_OVERRIDE
    else (REPO_ROOT / ".local" / "ops" / "xsp")
)

STATE_DIR = OPS_ROOT / "state"
BRAIN_PATH = STATE_DIR / "brain.json"
POSTS_DIR = STATE_DIR / "posts"

QUEUE_DIR = OPS_ROOT / "queue"
QUEUE_PENDING = QUEUE_DIR / "pending"
QUEUE_RUNNING = QUEUE_DIR / "running"
QUEUE_DONE = QUEUE_DIR / "done"
QUEUE_FAILED = QUEUE_DIR / "failed"

PACKETS_DIR = OPS_ROOT / "packets"
EVENTS_DIR = OPS_ROOT / "events"


def resolve_ops_root(root: Path | None = None) -> Path:
    """Return explicit root, else env XSP_OPS_ROOT, else default under repo."""
    if root is not None:
        return Path(root)
    override = os.environ.get("XSP_OPS_ROOT")
    if override:
        return Path(override)
    return REPO_ROOT / ".local" / "ops" / "xsp"


def ensure_layout(root: Path | None = None) -> Path:
    """Create ops directory tree. Returns ops root."""
    base = resolve_ops_root(root)
    for d in (
        base / "state" / "posts",
        base / "queue" / "pending",
        base / "queue" / "running",
        base / "queue" / "done",
        base / "queue" / "failed",
        base / "packets",
        base / "events",
    ):
        d.mkdir(parents=True, exist_ok=True)
    return base


def posts_path(slug: str, root: Path | None = None) -> Path:
    base = resolve_ops_root(root)
    return base / "state" / "posts" / f"{slug}.json"


def brain_path(root: Path | None = None) -> Path:
    base = resolve_ops_root(root)
    return base / "state" / "brain.json"


def queue_path(status: str, slug: str, root: Path | None = None) -> Path:
    base = resolve_ops_root(root)
    return base / "queue" / status / f"{slug}.json"


def packets_dir(root: Path | None = None) -> Path:
    return resolve_ops_root(root) / "packets"


def events_dir(root: Path | None = None) -> Path:
    return resolve_ops_root(root) / "events"
