"""Resume bookkeeping for test runs that span a reboot.

A reboot kills the pytest process.  The next boot starts pytest again (see
:mod:`harness.reboot.autostart`), so the resumed process has to know which
tests already ran and which ones still need to.  Completion records live next
to the run artifacts, which survive the reboot::

    <run-dir>/resume/completed.json   # {"completed": {"nodeid": "passed", ...}}
    <run-dir>/resume/attempts         # incremented by the resume wrapper

The logic is intentionally package-agnostic: any test suite can use it.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.artifacts.manifest import durable_write_text

__all__ = [
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


def load_completed(run_dir: Path | str) -> dict[str, str]:
    """Return a mapping of node id -> outcome for completed tests.

    Backwards-compatible: old format stored a list of node ids, which is
    converted to {nodeid: "passed"}.
    """
    path = _completed_path(run_dir)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    values = loaded.get("completed") if isinstance(loaded, dict) else None
    if isinstance(values, list):
        # Old format: list of node ids → assume passed.
        return {str(v): "passed" for v in values}
    if isinstance(values, dict):
        return {str(k): str(v) for k, v in values.items()}
    return {}


def record_completed(run_dir: Path | str, nodeid: str, outcome: str = "passed") -> None:
    """Record ``nodeid`` as completed with the given outcome.

    The record is flushed on every call so a reboot in the middle of the run
    cannot lose progress.
    """
    path = _completed_path(run_dir)
    completed = load_completed(run_dir)
    if nodeid in completed and completed[nodeid] == outcome:
        return
    completed[nodeid] = outcome
    payload = json.dumps({"completed": completed}, indent=2) + "\n"
    # Durable + atomic so a reboot seconds after a test completes cannot lose
    # the record (which would re-run an already-finished test).  Also fsyncs
    # the directory so the rename survives.
    durable_write_text(path, payload)
