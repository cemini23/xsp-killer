"""Filesystem work queue: pending jobs only (sensor never auto-advances)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xsp_killer.ops.paths import (
    QUEUE_DONE,
    QUEUE_FAILED,
    QUEUE_PENDING,
    QUEUE_RUNNING,
    ensure_layout,
    queue_path,
)
from xsp_killer.ops.state import read_json, utc_now_iso, write_json

VALID_STATUSES = ("pending", "running", "done", "failed")


def _status_dir(status: str, root: Path | None) -> Path:
    if root is None:
        return {
            "pending": QUEUE_PENDING,
            "running": QUEUE_RUNNING,
            "done": QUEUE_DONE,
            "failed": QUEUE_FAILED,
        }[status]
    return Path(root) / "queue" / status


def list_jobs(status: str, root: Path | None = None) -> list[dict[str, Any]]:
    ensure_layout(root)
    d = _status_dir(status, root)
    jobs: list[dict[str, Any]] = []
    if not d.is_dir():
        return jobs
    for path in sorted(d.glob("*.json")):
        data = read_json(path, {})
        if isinstance(data, dict):
            data.setdefault("slug", path.stem)
            data["_path"] = str(path)
            jobs.append(data)
    return jobs


def count_jobs(status: str, root: Path | None = None) -> int:
    ensure_layout(root)
    d = _status_dir(status, root)
    if not d.is_dir():
        return 0
    return len(list(d.glob("*.json")))


def find_job(slug: str, root: Path | None = None) -> tuple[str, dict[str, Any]] | None:
    """Return (status, job) if slug exists in any queue bucket."""
    ensure_layout(root)
    for status in VALID_STATUSES:
        path = queue_path(status, slug, root)
        if path.is_file():
            data = read_json(path, {})
            if isinstance(data, dict):
                data.setdefault("slug", slug)
                return status, data
    return None


def write_pending(
    slug: str,
    root: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Create pending job if not already queued anywhere (idempotent)."""
    ensure_layout(root)
    existing = find_job(slug, root)
    if existing is not None:
        status, _ = existing
        return queue_path(status, slug, root)

    job: dict[str, Any] = {
        "slug": slug,
        "created_at": utc_now_iso(),
        "status": "pending",
    }
    if extra:
        job.update(extra)
    path = queue_path("pending", slug, root)
    write_json(path, job)
    return path
