"""Run manifest schema and persistence.

A run is a directory under the artifacts root containing a ``manifest.json``.
This module owns the manifest contract: its fields, JSON encoding/decoding and
on-disk read/write. It is a leaf module and must not import the store or
retention.

On-disk form::

    {
      "run_id": "2026-10-23T14-05-00Z",
      "created": "2026-10-23T14:05:00Z",
      "status": "passed" | "failed" | "unknown",
      "summary": {"passed": 12, "failed": 0},
      "metadata": {"git_sha": "...", "screenshot_tool": "...", "display": {...}},
      "tests": [{"id": "tests/system76_power/test_profile.py::test_x", "status": "passed"}]
    }

Reading is tolerant: a missing or unparseable manifest returns ``None``. A
missing ``created`` is left as ``None`` so callers can fall back to other
sources (e.g. the run directory mtime). Status is derived from ``summary`` when
no explicit valid status is present, and defaults to ``"unknown"``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
VALID_STATUSES = frozenset({STATUS_PASSED, STATUS_FAILED})

__all__ = [
    "MANIFEST_NAME",
    "STATUS_PASSED",
    "STATUS_FAILED",
    "STATUS_UNKNOWN",
    "VALID_STATUSES",
    "Manifest",
    "durable_write_text",
    "manifest_path",
    "load_manifest",
    "write_manifest",
]


def _fsync_dir(directory: Path) -> None:
    """Best-effort fsync of a directory so a rename survives power loss."""
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def durable_write_text(path: Path | str, text: str) -> Path:
    """Write *text* durably: temp file -> fsync -> atomic rename -> dir fsync.

    Documents written here must survive an abrupt ``reboot(2)`` issued moments
    later: reboot-phase state and completion ledgers drive resume, and a lost
    or half-written file makes completed work re-run (or whole phases roll
    back).  Leaf helper so every JSON document in the harness shares one
    write path.
    """
    path = Path(path)
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        _fsync_dir(directory)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _derive_status(data: dict[str, Any], summary: dict[str, Any]) -> str:
    status = data.get("status")
    if isinstance(status, str) and status.lower() in VALID_STATUSES:
        return status.lower()
    failed = summary.get("failed")
    passed = summary.get("passed")
    if isinstance(failed, int) and failed > 0:
        return STATUS_FAILED
    # Un-run tests or unknown entries are non-passing: never read a run with
    # holes in it as a clean pass.
    for key in ("not_run", "unknown"):
        value = summary.get(key)
        if isinstance(value, int) and value > 0:
            return STATUS_UNKNOWN
    if isinstance(passed, int) and passed > 0:
        return STATUS_PASSED
    return STATUS_UNKNOWN


@dataclass
class Manifest:
    run_id: str
    created: datetime | None = None
    status: str = STATUS_UNKNOWN
    summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    tests: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        summary = data.get("summary")
        if not isinstance(summary, dict):
            summary = {}
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        tests = data.get("tests")
        if not isinstance(tests, list):
            tests = []
        run_id = data.get("run_id")
        if not isinstance(run_id, str):
            run_id = ""
        return cls(
            run_id=run_id,
            created=_parse_time(data.get("created")),
            status=_derive_status(data, summary),
            summary=summary,
            metadata=metadata,
            tests=tests,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created"] = _format_time(self.created)
        return data


def manifest_path(run_dir: Path) -> Path:
    return Path(run_dir) / MANIFEST_NAME


def load_manifest(run_dir: Path) -> Manifest | None:
    path = manifest_path(run_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return Manifest.from_dict(data)


def write_manifest(run_dir: Path, manifest: Manifest) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n"
    return durable_write_text(manifest_path(run_dir), text)
