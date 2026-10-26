"""Resume bookkeeping for test runs that span a reboot.

A reboot kills the pytest process.  The next boot starts pytest again (see
:mod:`harness.reboot.autostart`), so the resumed process has to know which
tests already ran and which ones still need to.  Completion records live next
to the run artifacts, which survive the reboot::

    <run-dir>/resume/completed.json   # {"completed": ["tests/...::test_x", ...]}
    <run-dir>/resume/attempts         # incremented by the resume wrapper

The logic is intentionally package-agnostic: any test suite can use it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = [
    "ResumeState",
    "bump_attempts",
    "load_completed",
    "record_completed",
    "resume_dir",
]


def resume_dir(run_dir: Path | str) -> Path:
    directory = Path(run_dir) / "resume"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _completed_path(run_dir: Path | str) -> Path:
    return resume_dir(run_dir) / "completed.json"


def load_completed(run_dir: Path | str) -> set[str]:
    """Return the node ids already completed in ``run_dir``."""
    path = _completed_path(run_dir)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    values = loaded.get("completed") if isinstance(loaded, dict) else None
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values}


def record_completed(run_dir: Path | str, nodeid: str) -> None:
    """Record ``nodeid`` as completed, atomically and immediately.

    The record is flushed on every call so a reboot in the middle of the run
    cannot lose progress.
    """
    path = _completed_path(run_dir)
    completed = load_completed(run_dir)
    if nodeid in completed:
        return
    completed.add(nodeid)
    payload = json.dumps({"completed": sorted(completed)}, indent=2) + "\n"
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def bump_attempts(run_dir: Path | str, *, limit: int = 10) -> bool:
    """Increment the resume counter and report whether another try is allowed."""
    path = resume_dir(run_dir) / "attempts"
    try:
        attempts = int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        attempts = 0
    attempts += 1
    path.write_text(f"{attempts}\n", encoding="utf-8")
    return attempts <= limit


class ResumeState:
    """Small convenience wrapper combining completion + attempt bookkeeping."""

    def __init__(self, run_dir: Path | str) -> None:
        self.run_dir = Path(run_dir)

    def completed(self) -> set[str]:
        return load_completed(self.run_dir)

    def mark(self, nodeid: str) -> None:
        record_completed(self.run_dir, nodeid)

    def next_attempt(self, *, limit: int = 10) -> bool:
        return bump_attempts(self.run_dir, limit=limit)
