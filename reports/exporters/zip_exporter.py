"""
ZIP archive builder for bulk report exports.

This module packages already-generated report files into a downloadable ZIP.
It performs no report generation and contains no business logic.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterable
from typing import Any

from reports.utils.filename_utils import make_unique_filename


def build_zip_from_items(
    bulk_report_items: Iterable[Any],
) -> tuple[bytes, dict[str, Any]]:
    """
    Build a ZIP archive containing generated report files.

    Returns
    -------
    tuple
        (zip_bytes, manifest)
    """
    buffer = io.BytesIO()
    manifest: dict[str, Any] = {}
    used_filenames: set[str] = set()

    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:

        for item in bulk_report_items:
            report = getattr(item, "generated_report", None)

            if report is None or not getattr(report, "file", None):
                continue

            filename = make_unique_filename(
                _build_filename(item, report),
                used_filenames,
            )
            used_filenames.add(filename)

            with report.file.open("rb") as report_file:
                archive.writestr(
                    filename,
                    report_file.read(),
                )

            manifest[filename] = {
                "generated_report_id": report.pk,
                "target_object_id": item.target_object_id,
                "report_type": getattr(
                    getattr(report, "report_type", None),
                    "code",
                    None,
                ),
            }

        archive.writestr(
            "manifest.json",
            json.dumps(
                manifest,
                indent=2,
                default=str,
            ),
        )

    return buffer.getvalue(), manifest


def _build_filename(
    item: Any,
    report: Any,
) -> str:
    """
    Build a deterministic filename for a generated report.
    """
    target = item.target_object

    identifier = (
        getattr(target, "student_number", None)
        or getattr(target, "registration_number", None)
        or getattr(target, "employee_number", None)
        or getattr(target, "pk", item.target_object_id)
    )

    report_type = getattr(
        getattr(report, "report_type", None),
        "code",
        "document",
    )

    extension = _guess_extension(report)

    return f"{report_type}_{identifier}{extension}"


def _guess_extension(report: Any) -> str:
    """
    Determine the file extension from the stored report filename.
    """
    filename = getattr(report.file, "name", "")

    suffix = zipfile.Path(filename).suffix

    return suffix or ".pdf"