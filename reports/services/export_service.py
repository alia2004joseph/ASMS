"""
Single entry point for rendering and persisting downloadable report files.

ViewSets, services, and Celery tasks call ``export()`` and
``persist_to_generated_report()`` rather than importing concrete exporters.
Adding a new format therefore requires registering it in ``_EXPORTER_CLASSES``
and ``_FORMAT_METADATA`` only.

The service is deliberately responsible for:
- validating export formats and rendered output;
- computing and validating content hashes;
- safely replacing stored files;
- updating generated-report lifecycle fields;
- recording failures without leaking unbounded exception text.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from reports.constants import ExportFormat, GeneratedReportStatus
from reports.exceptions import ValidationError
from reports.exporters.csv_exporter import CSVExporter
from reports.exporters.excel_exporter import ExcelExporter
from reports.exporters.pdf_exporter import PDFExporter


logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 4_000

_EXPORTER_CLASSES = {
    ExportFormat.PDF: PDFExporter,
    ExportFormat.EXCEL: ExcelExporter,
    ExportFormat.CSV: CSVExporter,
}

_FORMAT_METADATA = {
    ExportFormat.PDF: {
        "extension": "pdf",
        "mime_type": "application/pdf",
    },
    ExportFormat.EXCEL: {
        "extension": "xlsx",
        "mime_type": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    },
    ExportFormat.CSV: {
        "extension": "csv",
        "mime_type": "text/csv",
    },
    ExportFormat.ZIP: {
        "extension": "zip",
        "mime_type": "application/zip",
    },
}


def _normalise_export_format(export_format: str) -> str:
    if not isinstance(export_format, str) or not export_format.strip():
        raise ValidationError("A valid export format is required.")

    normalised = export_format.strip().upper()

    valid_values = {
        value
        for value, _label in ExportFormat.choices
    }
    if normalised not in valid_values:
        raise ValidationError(
            f"Unsupported export format: {export_format!r}."
        )

    return normalised


def _validate_report_data(report_data: Mapping[str, Any]) -> None:
    if not isinstance(report_data, Mapping):
        raise ValidationError("report_data must be a mapping/object.")


def _validate_file_bytes(file_bytes: bytes | bytearray | memoryview) -> bytes:
    if not isinstance(file_bytes, (bytes, bytearray, memoryview)):
        raise ValidationError(
            "Exporter must return bytes, bytearray, or memoryview."
        )

    rendered = bytes(file_bytes)
    if not rendered:
        raise ValidationError("Exporter returned an empty file.")

    return rendered


def _sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _safe_report_code(generated_report: Any) -> str:
    report_type = getattr(generated_report, "report_type", None)
    code = getattr(report_type, "code", None)

    if not code:
        code = getattr(generated_report, "document_type", None)

    if not code:
        code = generated_report.__class__.__name__

    return slugify(str(code)) or "generated-report"


def _build_filename(
    *,
    generated_report: Any,
    export_format: str,
) -> str:
    metadata = _FORMAT_METADATA[export_format]
    report_code = _safe_report_code(generated_report)
    unique_suffix = uuid.uuid4().hex
    return (
        f"{report_code}_{generated_report.pk}_{unique_suffix}."
        f"{metadata['extension']}"
    )


def export(
    *,
    report_data: Mapping[str, Any],
    export_format: str,
) -> tuple[bytes, str]:
    """
    Render report data and return ``(file_bytes, sha256_hash)``.

    Exporter instances are created per call to avoid accidental shared mutable
    state between concurrent requests or Celery workers.
    """
    _validate_report_data(report_data)
    normalised_format = _normalise_export_format(export_format)

    exporter_class = _EXPORTER_CLASSES.get(normalised_format)
    if exporter_class is None:
        raise ValidationError(
            f"Format '{normalised_format}' is not renderable by this service."
        )

    exporter = exporter_class()

    try:
        rendered = exporter.render(context=dict(report_data))
    except Exception:
        logger.exception(
            "Report export failed for format %s.",
            normalised_format,
        )
        raise

    file_bytes = _validate_file_bytes(rendered)

    exporter_hash = exporter.file_hash(file_bytes)
    calculated_hash = _sha256(file_bytes)

    if not isinstance(exporter_hash, str) or not exporter_hash.strip():
        raise ValidationError("Exporter returned an invalid file hash.")

    exporter_hash = exporter_hash.strip().lower()
    if exporter_hash != calculated_hash:
        raise ValidationError(
            "Exporter hash does not match the rendered file contents."
        )

    return file_bytes, calculated_hash


@transaction.atomic
def persist_to_generated_report(
    *,
    generated_report: Any,
    file_bytes: bytes,
    file_hash: str,
    export_format: str,
):
    """
    Persist rendered bytes and transition a generated report to READY.

    The database row is locked to prevent concurrent workers from overwriting
    each other. A new uniquely named file is written first; the previous file
    is deleted only after the model row has been saved successfully.
    """
    if getattr(generated_report, "pk", None) is None:
        raise ValidationError(
            "generated_report must be saved before attaching a file."
        )

    normalised_format = _normalise_export_format(export_format)
    rendered = _validate_file_bytes(file_bytes)
    calculated_hash = _sha256(rendered)

    if not isinstance(file_hash, str) or not file_hash.strip():
        raise ValidationError("A valid SHA-256 file hash is required.")

    if file_hash.strip().lower() != calculated_hash:
        raise ValidationError(
            "The supplied file hash does not match the file contents."
        )

    model_class = generated_report.__class__
    locked_report = model_class._default_manager.select_for_update().get(
        pk=generated_report.pk
    )

    filename = _build_filename(
        generated_report=locked_report,
        export_format=normalised_format,
    )
    old_file_name = (
        locked_report.file.name
        if getattr(locked_report, "file", None)
        else ""
    )

    locked_report.file.save(
        filename,
        ContentFile(rendered),
        save=False,
    )

    new_file_name = locked_report.file.name

    locked_report.file_hash = calculated_hash
    locked_report.file_size = len(rendered)
    locked_report.mime_type = _FORMAT_METADATA[normalised_format]["mime_type"]
    locked_report.export_format = normalised_format
    locked_report.status = GeneratedReportStatus.READY
    locked_report.created_at = timezone.now()

    update_fields = [
        "file",
        "file_hash",
        "export_format",
        "status",
        "created_at",
    ]

    if hasattr(locked_report, "file_size"):
        update_fields.append("file_size")
    if hasattr(locked_report, "mime_type"):
        update_fields.append("mime_type")
    if hasattr(locked_report, "failure_message"):
        locked_report.failure_message = ""
        update_fields.append("failure_message")
    elif hasattr(locked_report, "error_message"):
        locked_report.error_message = ""
        update_fields.append("error_message")

    try:
        locked_report.full_clean()
        locked_report.save(update_fields=update_fields)
    except Exception:
        try:
            if new_file_name:
                locked_report.file.storage.delete(new_file_name)
        except Exception:
            logger.exception(
                "Failed to delete orphaned generated-report file %s.",
                new_file_name,
            )
        raise

    if old_file_name and old_file_name != new_file_name:
        transaction.on_commit(
            lambda: _delete_old_file_safely(
                storage=locked_report.file.storage,
                file_name=old_file_name,
            )
        )

    logger.info(
        "Persisted generated report %s as %s.",
        locked_report.pk,
        normalised_format,
    )
    return locked_report


def _delete_old_file_safely(*, storage: Any, file_name: str) -> None:
    try:
        storage.delete(file_name)
    except Exception:
        logger.exception(
            "Failed to delete replaced generated-report file %s.",
            file_name,
        )


@transaction.atomic
def mark_failed(
    *,
    generated_report: Any,
    error_message: str,
):
    """
    Transition a generated report to FAILED and store a bounded error message.
    """
    if getattr(generated_report, "pk", None) is None:
        raise ValidationError(
            "generated_report must be saved before it can be marked failed."
        )

    model_class = generated_report.__class__
    locked_report = model_class._default_manager.select_for_update().get(
        pk=generated_report.pk
    )

    message = str(error_message or "Report generation failed.")
    message = message[:MAX_ERROR_MESSAGE_LENGTH]

    locked_report.status = GeneratedReportStatus.FAILED

    update_fields = ["status"]

    if hasattr(locked_report, "failure_message"):
        locked_report.failure_message = message
        update_fields.append("failure_message")
    elif hasattr(locked_report, "error_message"):
        locked_report.error_message = message
        update_fields.append("error_message")
    else:
        raise ValidationError(
            "Generated report model has no failure-message field."
        )

    locked_report.save(update_fields=update_fields)

    logger.warning(
        "Marked generated report %s as failed.",
        locked_report.pk,
    )
    return locked_report