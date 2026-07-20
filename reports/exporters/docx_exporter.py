"""
DOCX exporter for the Reports module.

This class establishes the production contract for Microsoft Word exports.
The rendering implementation is intentionally deferred until DOCX support is
introduced.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reports.exporters.base_exporter import BaseExporter


class DocxExporter(BaseExporter):
    """
    Microsoft Word (.docx) exporter.

    Once implemented, this exporter should use ``python-docx`` (or an
    equivalent library) to render reports while preserving the same context
    contract used by the PDF, Excel, and CSV exporters.

    Registering this exporter in the export service is sufficient to enable
    DOCX support—no callers should require modification.
    """

    format_code = "DOCX"
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    file_extension = ".docx"

    def render(
        self,
        *,
        context: Mapping[str, Any],
    ) -> bytes:
        """
        Render a report as a DOCX document.

        Raises
        ------
        NotImplementedError
            Until DOCX export support is implemented.
        """
        raise NotImplementedError(
            "DOCX export has not yet been implemented. "
            "Implement this exporter using python-docx and register it with "
            "the export service."
        )