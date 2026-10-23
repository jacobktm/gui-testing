"""Retention policy for run artifact directories.

Retention is applied at the artifacts root, across runs. A run is a real
subdirectory containing ``manifest.json`` (see :mod:`harness.artifacts.manifest`).
Rules receive the discovered runs, newest first, plus a context, and return the
set of run ids to keep. Runs not kept are deleted.

This module owns policy and discovery only; it does not define or write the
manifest schema.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, Sequence

from .manifest import STATUS_UNKNOWN, Manifest, load_manifest, manifest_path

__all__ = [
    "RunInfo",
    "RetentionContext",
    "RetentionRule",
    "RetentionPlan",
    "RetentionResult",
    "KeepAll",
    "KeepLast",
    "KeepFailures",
    "KeepNewerThan",
    "load_run",
    "discover_runs",
    "apply_retention",
]


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    path: Path
    created: datetime
    status: str
    manifest: Manifest | None = None
    summary: dict = field(default_factory=dict)
    subject: str | None = None

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def load_run(path: Path) -> RunInfo:
    """Build RunInfo for one run directory, tolerating a missing manifest."""
    manifest = load_manifest(path)

    created = manifest.created if manifest is not None else None
    if created is None:
        try:
            created = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            created = datetime.now(tz=timezone.utc)

    status = manifest.status if manifest is not None else STATUS_UNKNOWN
    summary = manifest.summary if manifest is not None else {}
    subject = None
    if manifest is not None and isinstance(manifest.metadata.get("subject"), str):
        subject = manifest.metadata["subject"]

    return RunInfo(
        run_id=path.name,
        path=path,
        created=created,
        status=status,
        manifest=manifest,
        summary=summary,
        subject=subject,
    )


def discover_runs(root: Path) -> list[RunInfo]:
    """Return manifest-bearing run directories under root, newest first."""
    if not root.is_dir():
        return []
    runs = [
        load_run(child)
        for child in root.iterdir()
        if child.is_dir()
        and not child.is_symlink()
        and manifest_path(child).is_file()
    ]
    runs.sort(key=lambda run: (run.created, run.run_id), reverse=True)
    return runs


@dataclass(frozen=True)
class RetentionContext:
    now: datetime
    current_run_id: str | None = None
    protected: frozenset[str] = frozenset()


class RetentionRule(Protocol):
    def keep(self, runs: Sequence[RunInfo], context: RetentionContext) -> set[str]: ...


@dataclass(frozen=True)
class KeepAll:
    def keep(self, runs: Sequence[RunInfo], context: RetentionContext) -> set[str]:
        return {run.run_id for run in runs}


@dataclass(frozen=True)
class KeepLast:
    count: int

    def keep(self, runs: Sequence[RunInfo], context: RetentionContext) -> set[str]:
        return {run.run_id for run in runs[: max(0, self.count)]}


@dataclass(frozen=True)
class KeepFailures:
    """Keep non-passing runs; unreadable manifests count as unknown, so kept."""

    def keep(self, runs: Sequence[RunInfo], context: RetentionContext) -> set[str]:
        return {run.run_id for run in runs if not run.passed}


@dataclass(frozen=True)
class KeepNewerThan:
    max_age: timedelta

    def keep(self, runs: Sequence[RunInfo], context: RetentionContext) -> set[str]:
        cutoff = context.now - self.max_age
        return {run.run_id for run in runs if run.created >= cutoff}


@dataclass(frozen=True)
class RetentionPlan:
    """Union of rules: a run is kept if any rule keeps it."""

    rules: tuple[RetentionRule, ...]

    def keep(self, runs: Sequence[RunInfo], context: RetentionContext) -> set[str]:
        kept: set[str] = set()
        for rule in self.rules:
            kept |= rule.keep(runs, context)
        return kept


@dataclass(frozen=True)
class RetentionResult:
    kept: tuple[str, ...]
    deleted: tuple[str, ...]
    skipped: tuple[str, ...]
    dry_run: bool

    @property
    def removed(self) -> tuple[str, ...]:
        return self.deleted if not self.dry_run else ()


def apply_retention(
    root: Path,
    plan: RetentionPlan,
    *,
    current_run_id: str | None = None,
    protected: Sequence[str] = (),
    dry_run: bool = False,
    now: datetime | None = None,
) -> RetentionResult:
    """Delete runs under root that the plan does not keep.

    The current run and any explicitly protected ids are always kept.
    Only manifest-bearing directories are considered. With ``dry_run``,
    ``deleted`` lists runs that *would* have been removed.
    """
    root = Path(root)
    context = RetentionContext(
        now=now or datetime.now(tz=timezone.utc),
        current_run_id=current_run_id,
        protected=frozenset(
            set(protected) | ({current_run_id} if current_run_id else set())
        ),
    )
    runs = discover_runs(root)
    keep = plan.keep(runs, context) | context.protected

    kept: list[str] = []
    deleted: list[str] = []
    skipped: list[str] = []
    for run in runs:
        if run.run_id in keep:
            kept.append(run.run_id)
            continue
        if not dry_run:
            try:
                shutil.rmtree(run.path)
            except OSError:
                skipped.append(run.run_id)
                continue
        deleted.append(run.run_id)

    return RetentionResult(
        kept=tuple(kept),
        deleted=tuple(deleted),
        skipped=tuple(skipped),
        dry_run=dry_run,
    )
