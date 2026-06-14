"""Strategic-report generation from the corrected workbook (Phase 3, A5)."""

from .generator import (
    ReportContext,
    ReportWriter,
    build_context,
    generate,
    get_report_writer,
    ungrounded_figures,
)

__all__ = [
    "ReportContext",
    "ReportWriter",
    "build_context",
    "generate",
    "get_report_writer",
    "ungrounded_figures",
]
