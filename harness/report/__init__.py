from .writer import ReportWriter

__all__ = ["ReportWriter"]


def write_summary_report(run) -> None:
    """Convenience wrapper: create a ReportWriter and write a text report."""
    return ReportWriter(run).write_text()
