"""
Orchestrates bulk document generation and ZIP packaging.

Bulk jobs never reimplement single-document generation logic. Each
``BulkReportItem`` is produced by calling the same domain service used for a
single document. This module is responsible only for:

- persisting bulk jobs and their targets;
- tracking item and job progress;
- finalising job status;
- packaging successful generated documents;
- expiring and cleaning up downloadable archives.

Celery orchestration belongs in ``reports.tasks``. All functions here are
plain Python/Django functions so they can be tested without a running worker.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.db.models import Model
from django.utils import timezone
from django.utils.text import slugify

from reports.constants import (
    BulkArchiveStatus,
    BulkItemStatus,
    BulkJobStatus,
)
from reports.models.bulk_jobs import (
    BulkExportArchive,
    BulkReportItem,
    BulkReportJob,
)

logger = logging.getLogger(__name__)

ARCHIVE_EXPIRY_HOURS = 72
ITEM_BULK_CREATE_BATCH_SIZE = 1_000

_TERMINAL_ITEM_STATUSES = {
    BulkItemStatus.SUCCESS,
    BulkItemStatus.FAILED,
}

_TERMINAL_JOB_STATUSES = {
    BulkJobStatus.COMPLETE,
    BulkJobStatus.PARTIAL_SUCCESS,
    BulkJobStatus.FAILED,
}


def _normalise_parameters(parameters: dict[str, Any] | None) -> dict[str, Any]:
    if parameters is None:
        return {}

    if not isinstance(parameters, dict):
        raise ValidationError(
            {"parameters": "Bulk job parameters must be a JSON object."}
        )

    return parameters


def _materialise_and_validate_targets(
    *,
    school: Model,
    target_objects: Iterable[Model],
) -> list[Model]:
    """
    Materialise targets once and validate their persistence and school scope.

    The caller remains responsible for authorisation and for deciding which
    targets belong in the job. This validation provides defence in depth so a
    cross-school target cannot accidentally be persisted.
    """
    targets = list(target_objects)

    if not targets:
        raise ValidationError(
            {"target_objects": "At least one target object is required."}
        )

    seen_targets: set[tuple[str, str, Any]] = set()

    for target in targets:
        if not isinstance(target, Model):
            raise ValidationError(
                {
                    "target_objects": (
                        "Every target must be a persisted Django model instance."
                    )
                }
            )

        if target.pk is None:
            raise ValidationError(
                {
                    "target_objects": (
                        f"{target.__class__.__name__} must be saved before it "
                        "can be added to a bulk job."
                    )
                }
            )

        target_school_id = getattr(target, "school_id", None)
        if target_school_id is None:
            raise ValidationError(
                {
                    "target_objects": (
                        f"{target.__class__.__name__} does not expose school_id "
                        "and cannot be safely used as a bulk-job target."
                    )
                }
            )

        if target_school_id != school.pk:
            raise ValidationError(
                {
                    "target_objects": (
                        f"{target.__class__.__name__} with primary key "
                        f"{target.pk!r} belongs to another school."
                    )
                }
            )

        identity = (
            target._meta.app_label,
            target._meta.model_name,
            target.pk,
        )
        if identity in seen_targets:
            raise ValidationError(
                {
                    "target_objects": (
                        f"Duplicate target detected: "
                        f"{target._meta.label}({target.pk!r})."
                    )
                }
            )

        seen_targets.add(identity)

    return targets


def _content_types_for_targets(
    targets: list[Model],
) -> dict[type[Model], ContentType]:
    model_classes = {type(target) for target in targets}
    return ContentType.objects.get_for_models(
        *model_classes,
        for_concrete_models=False,
    )


def _archive_filename(job: BulkReportJob) -> str:
    job_type = slugify(str(job.job_type)) or "bulk-export"
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"{job_type}_{job.pk}_{timestamp}.zip"


def _validate_manifest(
    *,
    manifest: Any,
    successful_item_count: int,
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValidationError(
            {"manifest": "ZIP exporter manifest must be a JSON object."}
        )

    normalised = dict(manifest)
    normalised.setdefault("version", 1)
    normalised.setdefault("created_at", timezone.now().isoformat())
    normalised.setdefault("item_count", successful_item_count)

    item_count = normalised.get("item_count")
    if (
        isinstance(item_count, bool)
        or not isinstance(item_count, int)
        or item_count < 0
    ):
        raise ValidationError(
            {"manifest": "Manifest item_count must be a non-negative integer."}
        )

    if item_count != successful_item_count:
        raise ValidationError(
            {
                "manifest": (
                    "Manifest item_count does not match the number of "
                    "successful bulk-report items."
                )
            }
        )

    return normalised


@transaction.atomic
def create_job(
    *,
    school: Model,
    job_type: str,
    requested_by: Model,
    parameters: dict[str, Any] | None,
    target_objects: Iterable[Model],
) -> BulkReportJob:
    """
    Persist a bulk job and one item per already-authorised target.

    Targets are materialised once so generators and querysets behave
    consistently. Cross-school and duplicate targets are rejected.
    """
    if school.pk is None:
        raise ValidationError({"school": "School must be persisted."})

    if requested_by.pk is None:
        raise ValidationError(
            {"requested_by": "Requesting user must be persisted."}
        )

    requester_school_id = getattr(requested_by, "school_id", None)
    requester_is_superuser = bool(
        getattr(requested_by, "is_superuser", False)
    )
    if (
        requester_school_id is not None
        and requester_school_id != school.pk
        and not requester_is_superuser
    ):
        raise ValidationError(
            {
                "requested_by": (
                    "The requesting user must belong to the same school as "
                    "the bulk job."
                )
            }
        )

    if hasattr(requested_by, "is_active") and not requested_by.is_active:
        raise ValidationError(
            {"requested_by": "An inactive user cannot request a bulk job."}
        )

    normalised_parameters = _normalise_parameters(parameters)
    targets = _materialise_and_validate_targets(
        school=school,
        target_objects=target_objects,
    )
    content_types = _content_types_for_targets(targets)

    job = BulkReportJob(
        school=school,
        job_type=job_type,
        requested_by=requested_by,
        parameters=normalised_parameters,
        total_items=len(targets),
        completed_items=0,
        failed_items=0,
        status=BulkJobStatus.PENDING,
    )
    job.full_clean()
    job.save()

    items = [
        BulkReportItem(
            job=job,
            target_content_type=content_types[type(target)],
            target_object_id=target.pk,
            status=BulkItemStatus.PENDING,
        )
        for target in targets
    ]

    BulkReportItem.objects.bulk_create(
        items,
        batch_size=ITEM_BULK_CREATE_BATCH_SIZE,
    )

    logger.info(
        "Created bulk report job %s with %s items.",
        job.pk,
        len(items),
    )
    return job


@transaction.atomic
def mark_job_processing(job: BulkReportJob) -> BulkReportJob:
    """
    Atomically move a pending job into processing.

    The operation is idempotent. Repeated calls for an already-processing job
    return the current row without resetting ``started_at``.
    """
    locked_job = BulkReportJob.objects.select_for_update().get(pk=job.pk)

    if locked_job.status in _TERMINAL_JOB_STATUSES:
        raise ValidationError(
            {
                "status": (
                    "A completed, partially successful, or failed job cannot "
                    "be moved back to processing."
                )
            }
        )

    if locked_job.status == BulkJobStatus.PROCESSING:
        return locked_job

    locked_job.status = BulkJobStatus.PROCESSING
    if locked_job.started_at is None:
        locked_job.started_at = timezone.now()

    locked_job.save(update_fields=["status", "started_at"])

    logger.info("Bulk report job %s started processing.", locked_job.pk)
    return locked_job


@transaction.atomic
def record_item_result(
    *,
    item: BulkReportItem,
    success: bool,
    generated_report: Model | None = None,
    error_message: str = "",
) -> BulkReportItem:
    """
    Persist a terminal result for one bulk item.

    The row is locked to prevent concurrent workers from overwriting one
    another. Repeating the same terminal result is treated as idempotent;
    attempting to change an already-terminal result raises a validation error.
    """
    locked_item = (
        BulkReportItem.objects.select_for_update()
        .select_related("job")
        .get(pk=item.pk)
    )

    desired_status = (
        BulkItemStatus.SUCCESS if success else BulkItemStatus.FAILED
    )

    if locked_item.status in _TERMINAL_ITEM_STATUSES:
        same_result = (
            locked_item.status == desired_status
            and locked_item.generated_report_id
            == getattr(generated_report, "pk", None)
            and locked_item.error_message == (error_message or "")
        )
        if same_result:
            return locked_item

        raise ValidationError(
            {
                "status": (
                    "This bulk-report item already has a terminal result and "
                    "cannot be overwritten."
                )
            }
        )

    if success and generated_report is None:
        raise ValidationError(
            {
                "generated_report": (
                    "A successful bulk-report item must reference its "
                    "generated report."
                )
            }
        )

    if not success and generated_report is not None:
        raise ValidationError(
            {
                "generated_report": (
                    "A failed bulk-report item cannot reference a generated "
                    "report."
                )
            }
        )

    if success and error_message:
        raise ValidationError(
            {
                "error_message": (
                    "A successful bulk-report item cannot have an error "
                    "message."
                )
            }
        )

    generated_school_id = getattr(generated_report, "school_id", None)
    if (
        generated_report is not None
        and generated_school_id is not None
        and generated_school_id != locked_item.job.school_id
    ):
        raise ValidationError(
            {
                "generated_report": (
                    "The generated report must belong to the same school as "
                    "the bulk job."
                )
            }
        )

    locked_item.status = desired_status
    locked_item.generated_report = generated_report
    locked_item.error_message = "" if success else (error_message or "")[:4000]
    locked_item.save(
        update_fields=[
            "status",
            "generated_report",
            "error_message",
        ]
    )

    return locked_item


@transaction.atomic
def finalize_job(job: BulkReportJob) -> BulkReportJob:
    """
    Recalculate terminal item totals and atomically finalise the job.

    A job may be finalised only after every item has reached SUCCESS or FAILED.
    """
    locked_job = BulkReportJob.objects.select_for_update().get(pk=job.pk)

    counts = {
        row["status"]: row["count"]
        for row in (
            locked_job.items.values("status")
            .annotate(count=models.Count("id"))
        )
    }

    completed = counts.get(BulkItemStatus.SUCCESS, 0)
    failed = counts.get(BulkItemStatus.FAILED, 0)
    terminal_total = completed + failed

    if terminal_total != locked_job.total_items:
        raise ValidationError(
            {
                "status": (
                    "The job cannot be finalised until every item has reached "
                    "a terminal status."
                )
            }
        )

    locked_job.completed_items = completed
    locked_job.failed_items = failed
    locked_job.finished_at = timezone.now()

    if failed == 0:
        locked_job.status = BulkJobStatus.COMPLETE
    elif completed == 0:
        locked_job.status = BulkJobStatus.FAILED
    else:
        locked_job.status = BulkJobStatus.PARTIAL_SUCCESS

    locked_job.save(
        update_fields=[
            "completed_items",
            "failed_items",
            "finished_at",
            "status",
        ]
    )

    logger.info(
        "Finalised bulk report job %s: %s successful, %s failed.",
        locked_job.pk,
        completed,
        failed,
    )
    return locked_job


@transaction.atomic
def build_archive(job: BulkReportJob) -> BulkExportArchive | None:
    """
    Package successful item files into a downloadable ZIP archive.

    The operation is idempotent: an existing non-expired READY archive for the
    job is returned rather than creating a duplicate.
    """
    from reports.exporters.zip_exporter import build_zip_from_items

    locked_job = BulkReportJob.objects.select_for_update().get(pk=job.pk)

    if locked_job.status not in {
        BulkJobStatus.COMPLETE,
        BulkJobStatus.PARTIAL_SUCCESS,
    }:
        raise ValidationError(
            {
                "status": (
                    "An archive can be built only for a complete or partially "
                    "successful bulk job."
                )
            }
        )

    now = timezone.now()
    existing_archive = (
        BulkExportArchive.objects.select_for_update()
        .filter(
            job=locked_job,
            status=BulkArchiveStatus.READY,
            expires_at__gt=now,
        )
        .exclude(zip_file="")
        .order_by("-created_at", "-pk")
        .first()
    )
    if existing_archive is not None:
        return existing_archive

    successful_items = (
        locked_job.items.filter(status=BulkItemStatus.SUCCESS)
        .select_related("generated_report")
        .order_by("pk")
    )
    successful_item_count = successful_items.count()

    if successful_item_count == 0:
        return None

    try:
        zip_bytes, raw_manifest = build_zip_from_items(successful_items)
    except Exception:
        logger.exception(
            "ZIP exporter failed for bulk report job %s.",
            locked_job.pk,
        )
        raise

    if not isinstance(zip_bytes, (bytes, bytearray)) or not zip_bytes:
        raise ValidationError(
            {"zip_file": "ZIP exporter returned an empty or invalid archive."}
        )

    manifest = _validate_manifest(
        manifest=raw_manifest,
        successful_item_count=successful_item_count,
    )

    archive = BulkExportArchive(
        school=locked_job.school,
        job=locked_job,
        manifest=manifest,
        expires_at=now + timedelta(hours=ARCHIVE_EXPIRY_HOURS),
        status=BulkArchiveStatus.READY,
        created_at=now,
    )

    filename = _archive_filename(locked_job)
    archive.zip_file.save(
        filename,
        ContentFile(bytes(zip_bytes)),
        save=False,
    )

    try:
        archive.full_clean()
        archive.save()
    except Exception:
        if archive.zip_file:
            try:
                archive.zip_file.delete(save=False)
            except Exception:
                logger.exception(
                    "Failed to remove orphaned archive file %s.",
                    archive.zip_file.name,
                )
        raise

    logger.info(
        "Created bulk export archive %s for job %s.",
        archive.pk,
        locked_job.pk,
    )
    return archive


def is_archive_expired(archive: BulkExportArchive) -> bool:
    """Return whether the archive has passed its expiry timestamp."""
    return (
        archive.expires_at is not None
        and timezone.now() >= archive.expires_at
    )


def get_job_progress(job: BulkReportJob) -> dict[str, int | float | str]:
    """
    Return current job progress using persisted counters and live pending count.
    """
    total = job.total_items
    successful = job.completed_items
    failed = job.failed_items
    terminal = successful + failed
    remaining = max(total - terminal, 0)
    percentage = round((terminal / total) * 100, 2) if total else 100.0

    return {
        "status": job.status,
        "total": total,
        "successful": successful,
        "failed": failed,
        "remaining": remaining,
        "percentage": percentage,
    }


def cleanup_expired_archives(*, batch_size: int = 500) -> int:
    """
    Delete stored ZIP files for expired archives and mark them EXPIRED.

    Intended for a scheduled Celery Beat task. Each archive is processed in its
    own transaction so one storage failure does not roll back the entire batch.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    expired_ids = list(
        BulkExportArchive.objects.filter(
            expires_at__lte=timezone.now(),
        )
        .exclude(status=BulkArchiveStatus.EXPIRED)
        .order_by("pk")
        .values_list("pk", flat=True)[:batch_size]
    )

    cleaned = 0

    for archive_id in expired_ids:
        try:
            with transaction.atomic():
                archive = (
                    BulkExportArchive.objects.select_for_update()
                    .get(pk=archive_id)
                )

                if archive.expires_at is None or archive.expires_at > timezone.now():
                    continue

                stored_name = (
                    archive.zip_file.name if archive.zip_file else ""
                )

                if archive.zip_file:
                    archive.zip_file.delete(save=False)

                archive.zip_file = None
                archive.status = BulkArchiveStatus.EXPIRED
                archive.save(update_fields=["zip_file", "status"])
                cleaned += 1

                logger.info(
                    "Expired bulk export archive %s (%s).",
                    archive.pk,
                    Path(stored_name).name if stored_name else "no file",
                )
        except Exception:
            logger.exception(
                "Failed to clean expired bulk export archive %s.",
                archive_id,
            )

    return cleaned