"""
PDF exporter for the Reports module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from django.template.loader import render_to_string

from reports.exporters.base_exporter import BaseExporter


class PDFExporter(BaseExporter):
    """
    Render reports as PDF documents using Django templates and WeasyPrint.
    """

    format_code = "PDF"
    content_type = "application/pdf"
    file_extension = ".pdf"

    def render(
        self,
        *,
        context: Mapping[str, Any],
    ) -> bytes:
        from weasyprint import HTML

        template_path = context["template_path"]
        html = render_to_string(template_path, context)

        return HTML(
            string=html,
            base_url=context.get("base_url"),
        ).write_pdf()

    def render_sheet(
        self,
        *,
        contexts: Sequence[Mapping[str, Any]],
        columns: int = 2,
        gap_px: int = 8,
    ) -> bytes:
        """
        Render multiple cards/documents on a single printable sheet.
        """
        from weasyprint import HTML

        if not contexts:
            raise ValueError("At least one rendering context is required.")

        template_path = contexts[0]["template_path"]
        base_url = contexts[0].get("base_url")

        cards = [
            render_to_string(template_path, ctx)
            for ctx in contexts
        ]

        html = f"""
        <html>
        <body>
            <div style="
                display:grid;
                grid-template-columns:repeat({columns},1fr);
                gap:{gap_px}px;
                align-items:start;
            ">
                {''.join(cards)}
            </div>
        </body>
        </html>
        """

        return HTML(
            string=html,
            base_url=base_url,
        ).write_pdf()