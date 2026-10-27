"""Human-readable test result reports for a run.

Operates on a :class:`harness.artifacts.RunArtifacts` instance and writes a
summary to ``<run_dir>/test_report.txt``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["write_summary_report"]


def write_summary_report(run) -> None:
    """Generate and write a human-readable test result report.

    Parameters
    ----------
    run:
        A :class:`harness.artifacts.RunArtifacts` instance (or any object
        with ``run_id``, ``run_dir``, and ``manifest`` attributes).
    """
    if run is None:
        return
    try:
        lines = []
        lines.append("=" * 60)
        lines.append("TEST RESULT REPORT")
        lines.append("=" * 60)
        lines.append(f"Run ID: {run.run_id}")
        lines.append(f"Run dir: {run.run_dir}")
        lines.append("")
        # Count statuses
        counts: dict[str, int] = {}
        for entry in run.manifest.tests:
            status = entry.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        counts["total"] = len(run.manifest.tests)
        lines.append("Summary:")
        for key in ("passed", "failed", "skipped", "unknown", "total"):
            if key in counts:
                lines.append(f"  {key}: {counts[key]}")
        lines.append("")
        lines.append("Per-test results:")
        for entry in run.manifest.tests:
            tid = entry.get("id", "?")
            status = entry.get("status", "unknown")
            summary = entry.get("summary", "")
            lines.append(f"  [{status.upper()}] {tid}: {summary}")
        lines.append("")
        lines.append("=" * 60)
        report = "\n".join(lines) + "\n"
        report_path = Path(run.run_dir) / "test_report.txt"
        report_path.write_text(report, encoding="utf-8")
        print(report)
    except Exception:
        pass
