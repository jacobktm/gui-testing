"""Report writers for test runs.

Exposes a :class:`ReportWriter` object with a predictable API so new output
formats (HTML, PDF, …) can be added without changing call sites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["ReportWriter"]


class ReportWriter:
    """Generate reports for a test run.

    Parameters
    ----------
    run:
        A :class:`harness.artifacts.RunArtifacts` instance (or any object
        with ``run_id``, ``run_dir``, and ``manifest`` attributes).
    """

    def __init__(self, run: Any) -> None:
        self.run = run

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def write(self, fmt: str = "text") -> Path | None:
        """Write a report in the given format and return the output path.

        Supported formats: ``"text"`` (default).  Future formats (``"html"``,
        ``"pdf"``, …) will be added here.
        """
        fmt = fmt.lower()
        if fmt == "text":
            return self.write_text()
        raise ValueError(f"unsupported report format: {fmt!r}")

    def write_text(self) -> Path | None:
        """Write a human-readable text report to ``<run_dir>/test_report.txt``."""
        run = self.run
        if run is None:
            return None
        try:
            lines = []
            lines.append("=" * 60)
            lines.append("TEST RESULT REPORT")
            lines.append("=" * 60)
            lines.append(f"Run ID: {run.run_id}")
            lines.append(f"Run dir: {run.run_dir}")
            lines.append("")
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
            return report_path
        except Exception:
            return None

    def write_html(self) -> Path | None:
        """Write an HTML report (not yet implemented)."""
        raise NotImplementedError("HTML reports are not yet implemented")

    def write_pdf(self) -> Path | None:
        """Write a PDF report (not yet implemented)."""
        raise NotImplementedError("PDF reports are not yet implemented")
