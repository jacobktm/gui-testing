"""Run-scoped artifact storage.

A :class:`RunArtifacts` owns one run directory under the artifacts root. It
creates the run manifest, writes evidence into per-checklist-item phase
directories, and records every artifact in the manifest so each screenshot,
detection, and log is attributable to the checklist item it validates.

Layout::

    <root>/<run_id>/
      manifest.json
      items/<checklist-item-id>/<phase>/
        001-step.png
        002-step.json

Evidence is indexed in ``manifest.tests`` as item records::

    {
      "id": "gnome.brightness_balanced_max",
      "status": "passed",
      "summary": "...",
      "metadata": {...},
      "evidence": [
        {
          "item": "gnome.brightness_balanced_max",
          "path": "items/.../before/001-step.png",
          "kind": "screenshot",
          "phase": "before",
          "step": "open_power_panel",
          "created": "2026-10-23T14:05:00Z",
          "source": "Screenshot from ....png",
          "metadata": {...}
        }
      ]
    }

The manifest is rewritten atomically after every change, so evidence survives
failures and reboots. Retention is applied only when explicitly requested by
``finalize``.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .manifest import (
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_UNKNOWN,
    Manifest,
    load_manifest,
    write_manifest,
)
from .retention import RetentionPlan, RetentionResult, apply_retention

STATUS_SKIPPED = "skipped"
ITEM_STATUSES = frozenset(
    {STATUS_PASSED, STATUS_FAILED, STATUS_SKIPPED, STATUS_UNKNOWN}
)

__all__ = [
    "ArtifactError",
    "ITEM_STATUSES",
    "RunArtifacts",
    "SavedArtifact",
    "STATUS_SKIPPED",
]


class ArtifactError(RuntimeError):
    """Raised when an artifact cannot be created or recorded."""


@dataclass(frozen=True)
class SavedArtifact:
    path: Path
    relative_path: str
    kind: str
    phase: str
    step: str | None
    created: datetime


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_run_id(now: datetime) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def _component(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError(f"{field} must be a non-empty string")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    if cleaned in {"", ".", ".."}:
        raise ArtifactError(f"invalid {field}: {value!r}")
    if cleaned.startswith("."):
        cleaned = "_" + cleaned.lstrip(".")
    return cleaned[:128]


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _next_sequence(directory: Path) -> int:
    highest = 0
    for child in directory.iterdir():
        match = re.match(r"(\d+)-", child.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _derive_status(items: Sequence[dict[str, Any]]) -> str:
    statuses = {entry.get("status") for entry in items}
    if STATUS_FAILED in statuses:
        return STATUS_FAILED
    if STATUS_PASSED in statuses:
        return STATUS_PASSED
    return STATUS_UNKNOWN


class RunArtifacts:
    def __init__(self, root: Path, run_dir: Path, manifest: Manifest) -> None:
        self.root = Path(root)
        self.run_dir = Path(run_dir)
        self.manifest = manifest

    @classmethod
    def create(
        cls,
        root: Path | str,
        *,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> RunArtifacts:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        now = now or datetime.now(tz=timezone.utc)
        run_id = _component(run_id or _new_run_id(now), "run id")
        run_dir = root / run_id
        run_dir.mkdir()
        manifest = Manifest(
            run_id=run_id,
            created=now,
            metadata=dict(metadata or {}),
        )
        write_manifest(run_dir, manifest)
        return cls(root, run_dir, manifest)

    @classmethod
    def load(cls, run_dir: Path | str, *, root: Path | str | None = None) -> RunArtifacts:
        run_dir = Path(run_dir)
        manifest = load_manifest(run_dir)
        if manifest is None:
            raise ArtifactError(f"no readable manifest in {run_dir}")
        if not manifest.run_id:
            manifest.run_id = run_dir.name
        return cls(Path(root) if root is not None else run_dir.parent, run_dir, manifest)

    @property
    def run_id(self) -> str:
        return self.manifest.run_id

    @property
    def items(self) -> tuple[str, ...]:
        return tuple(entry.get("id", "") for entry in self.manifest.tests)

    def item_dir(self, item_id: str) -> Path:
        item_id = _component(item_id, "item id")
        return self.run_dir / "items" / item_id

    def phase_dir(self, item_id: str, phase: str, *, create: bool = True) -> Path:
        item_id = _component(item_id, "item id")
        phase = _component(phase, "phase")
        directory = self.item_dir(item_id) / phase
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory

    def record_item(
        self,
        item_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        item_id = _component(item_id, "item id")
        entry = self._item(item_id)
        if status is not None:
            normalized = status.strip().lower()
            if normalized not in ITEM_STATUSES:
                raise ArtifactError(f"invalid item status: {status!r}")
            entry["status"] = normalized
        if summary is not None:
            entry["summary"] = summary
        if metadata:
            entry.setdefault("metadata", {}).update(metadata)
        self._save()

    def save_screenshot(
        self,
        item_id: str,
        phase: str,
        source: Path | str,
        *,
        step: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        move: bool = True,
    ) -> SavedArtifact:
        source = Path(source)
        if not source.is_file():
            raise ArtifactError(f"screenshot source does not exist: {source}")
        item_id, phase = self._normalize(item_id, phase)
        destination = self._destination(
            item_id,
            phase,
            name=name,
            step=step,
            kind="screenshot",
            suffix=source.suffix or ".png",
        )
        if source.resolve() != destination.resolve():
            if move:
                shutil.move(str(source), str(destination))
            else:
                shutil.copy2(source, destination)
        return self._record(
            item_id,
            phase,
            destination,
            kind="screenshot",
            step=step,
            metadata=metadata,
            source_name=source.name,
        )

    def save_detection(
        self,
        item_id: str,
        phase: str,
        payload: dict[str, Any],
        *,
        step: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SavedArtifact:
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        return self._save_text(
            item_id,
            phase,
            text,
            kind="detection",
            suffix=".json",
            step=step,
            name=name,
            metadata=metadata,
        )

    def save_text(
        self,
        item_id: str,
        phase: str,
        text: str,
        *,
        step: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        suffix: str = ".txt",
    ) -> SavedArtifact:
        return self._save_text(
            item_id,
            phase,
            text,
            kind="text",
            suffix=suffix,
            step=step,
            name=name,
            metadata=metadata,
        )

    def finalize(
        self,
        *,
        status: str | None = None,
        summary: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        retention_plan: RetentionPlan | None = None,
        protected: Sequence[str] = (),
        now: datetime | None = None,
    ) -> RetentionResult | None:
        if metadata:
            self.manifest.metadata.update(metadata)
        if summary is None:
            summary = self._summary()
        if status is None:
            status = _derive_status(self.manifest.tests)
        else:
            status = status.strip().lower()
            if status not in {STATUS_PASSED, STATUS_FAILED, STATUS_UNKNOWN}:
                raise ArtifactError(f"invalid run status: {status!r}")
        self.manifest.status = status
        self.manifest.summary = summary
        self._save()
        if retention_plan is None:
            return None
        return apply_retention(
            self.root,
            retention_plan,
            current_run_id=self.run_id,
            protected=protected,
            now=now,
        )

    def _normalize(self, item_id: str, phase: str) -> tuple[str, str]:
        return _component(item_id, "item id"), _component(phase, "phase")

    def _item(self, item_id: str) -> dict[str, Any]:
        for entry in self.manifest.tests:
            if entry.get("id") == item_id:
                entry.setdefault("metadata", {})
                entry.setdefault("evidence", [])
                return entry
        entry = {
            "id": item_id,
            "status": STATUS_UNKNOWN,
            "summary": "",
            "metadata": {},
            "evidence": [],
        }
        self.manifest.tests.append(entry)
        return entry

    def _destination(
        self,
        item_id: str,
        phase: str,
        *,
        name: str | None,
        step: str | None,
        kind: str,
        suffix: str,
    ) -> Path:
        directory = self.phase_dir(item_id, phase)
        if name:
            base = Path(name)
            stem = _component(base.stem, "artifact name")
            suffix = base.suffix or suffix
        else:
            sequence = _next_sequence(directory)
            label = _component(step or kind, "step")
            stem = f"{sequence:03d}-{label}"
        return _unique(directory / f"{stem}{suffix}")

    def _save_text(
        self,
        item_id: str,
        phase: str,
        text: str,
        *,
        kind: str,
        suffix: str,
        step: str | None,
        name: str | None,
        metadata: dict[str, Any] | None,
    ) -> SavedArtifact:
        item_id, phase = self._normalize(item_id, phase)
        destination = self._destination(
            item_id,
            phase,
            name=name,
            step=step,
            kind=kind,
            suffix=suffix,
        )
        destination.write_text(text, encoding="utf-8")
        return self._record(
            item_id,
            phase,
            destination,
            kind=kind,
            step=step,
            metadata=metadata,
        )

    def _record(
        self,
        item_id: str,
        phase: str,
        destination: Path,
        *,
        kind: str,
        step: str | None,
        metadata: dict[str, Any] | None,
        source_name: str | None = None,
    ) -> SavedArtifact:
        created = datetime.now(tz=timezone.utc)
        relative = destination.relative_to(self.run_dir).as_posix()
        entry = self._item(item_id)
        entry["evidence"].append(
            {
                "item": item_id,
                "path": relative,
                "kind": kind,
                "phase": phase,
                "step": step,
                "created": _isoformat(created),
                "source": source_name,
                "metadata": dict(metadata or {}),
            }
        )
        self._save()
        return SavedArtifact(
            path=destination,
            relative_path=relative,
            kind=kind,
            phase=phase,
            step=step,
            created=created,
        )

    def _summary(self) -> dict[str, Any]:
        counts: dict[str, Any] = {}
        for entry in self.manifest.tests:
            status = entry.get("status", STATUS_UNKNOWN)
            counts[status] = counts.get(status, 0) + 1
        counts["total"] = len(self.manifest.tests)
        return counts

    def _save(self) -> None:
        write_manifest(self.run_dir, self.manifest)
