"""
CSV exporter implementation for the Reports module.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

from reports.exporters.base_exporter import BaseExporter


class CSVExporter(BaseExporter):
    """
    Export report data as UTF-8 encoded CSV.
    """

    format_code = "CSV"
    content_type = "text/csv"
    file_extension = ".csv"

    def render(
        self,
        *,
        context: Mapping[str, Any],
    ) -> bytes:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)

        self._write_headers(writer, context.get("headers", ()))
        self._write_body(writer, context)
        self._write_grand_total(writer, context.get("grand_total"))

        return buffer.getvalue().encode("utf-8")

    @staticmethod
    def _write_headers(
        writer: csv.writer,
        headers: Sequence[Any],
    ) -> None:
        if headers:
            writer.writerow(headers)

    def _write_body(
        self,
        writer: csv.writer,
        context: Mapping[str, Any],
    ) -> None:
        groups = context.get("groups")

        if groups:
            self._write_groups(writer, groups)
            return

        for row in context.get("rows", ()):
            writer.writerow(row)

    @staticmethod
    def _write_groups(
        writer: csv.writer,
        groups: Sequence[Mapping[str, Any]],
    ) -> None:
        for group in groups:
            writer.writerow((group.get("label", ""),))

            for row in group.get("rows", ()):
                writer.writerow(row)

            subtotal = group.get("subtotal")
            if subtotal is not None:
                writer.writerow(("Subtotal", *subtotal))

    @staticmethod
    def _write_grand_total(
        writer: csv.writer,
        grand_total: Sequence[Any] | None,
    ) -> None:
        if grand_total is not None:
            writer.writerow(("Grand Total", *grand_total))