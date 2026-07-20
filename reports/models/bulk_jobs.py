import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from reports.constants import (
    BulkItemStatus,
    BulkJobStatus,
    BulkJobType,
)
from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedModel,
)


def _archive_upload_path(instance, filename):
    """
    Store ZIP archives without exposing original filenames.
    """
    extension = Path(filename).suffix.lower() or ".zip"

    return (
        f"reports/{instance.school_id}/bulk_archives/"
        f"{uuid.uuid4().hex}{extension}"
    )


class BulkReportJob(SchoolScopedModel):
    """
    Represents a bulk report generation request.

    Actual generation is performed asynchronously by Celery workers.
    """

    job_type = models.CharField(
        max_length=30,
        choices=BulkJobType.choices,
        db_index=True,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_report_jobs",
    )

    parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Immutable snapshot of the generation parameters."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=BulkJobStatus.choices,
        default=BulkJobStatus.PENDING,
        db_index=True,
    )

    total_items = models.PositiveIntegerField(default=0)
    completed_items = models.PositiveIntegerField(default=0)
    failed_items = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

        constraints = [
        models.CheckConstraint(
            condition=Q(total_items__gte=0),
            name="bulk_job_total_non_negative",
        ),
        models.CheckConstraint(
            condition=Q(completed_items__gte=0),
            name="bulk_job_completed_non_negative",
        ),
        models.CheckConstraint(
            condition=Q(failed_items__gte=0),
            name="bulk_job_failed_non_negative",
        ),
        models.CheckConstraint(
            condition=Q(
                completed_items__lte=F("total_items") - F("failed_items")
            ),
            name="bulk_job_progress_valid",
        ),
    ]

        indexes = [
            models.Index(
                fields=["school", "status", "-created_at"],
                name="bulk_job_status_idx",
            ),
            models.Index(
                fields=["school", "job_type"],
                name="bulk_job_type_idx",
            ),
            models.Index(
                fields=["requested_by", "-created_at"],
                name="bulk_job_requester_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.completed_items + self.failed_items
            > self.total_items
        ):
            raise ValidationError(
                "Completed items plus failed items cannot exceed total items."
            )

    @property
    def progress_percentage(self):
        if self.total_items == 0:
            return 0

        return round(
            ((self.completed_items + self.failed_items)
             / self.total_items) * 100,
            2,
        )

    def __str__(self):
        return (
            f"{self.get_job_type_display()} "
            f"({self.completed_items}/{self.total_items})"
        )


class BulkReportItem(models.Model):
    """
    Individual unit of work inside a bulk generation job.
    """

    job = models.ForeignKey(
        BulkReportJob,
        on_delete=models.CASCADE,
        related_name="items",
    )

    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="+",
    )

    target_object_id = models.PositiveBigIntegerField()

    target_object = GenericForeignKey(
        "target_content_type",
        "target_object_id",
    )

    status = models.CharField(
        max_length=20,
        choices=BulkItemStatus.choices,
        default=BulkItemStatus.PENDING,
        db_index=True,
    )

    generated_report = models.ForeignKey(
        "reports.GeneratedReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )

    error_message = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        ordering = ["id"]

        indexes = [
            models.Index(
                fields=["job", "status"],
                name="bulk_item_status_idx",
            ),
            models.Index(
                fields=[
                    "target_content_type",
                    "target_object_id",
                ],
                name="bulk_item_target_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.job_id} : "
            f"{self.get_status_display()}"
        )


class BulkExportArchive(
    AbstractGeneratedArtifact,
    SchoolScopedModel,
):
    """
    ZIP archive containing all successfully generated reports for a bulk job.

    The inherited 'file' field stores the archive itself.

    'manifest' maps archived filenames to generated report identifiers and
    source objects for audit and troubleshooting.
    """

    job = models.OneToOneField(
        BulkReportJob,
        on_delete=models.CASCADE,
        related_name="archive",
    )

    manifest = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Maps archive filenames to generated reports and source items."
        ),
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    downloaded_count = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=Q(downloaded_count__gte=0),
                name="bulk_archive_downloads_positive",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "expires_at"],
                name="bulk_archive_expiry_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if self.downloaded_count < 0:
            raise ValidationError(
                {
                    "downloaded_count":
                    "Download count cannot be negative."
                }
            )

    def __str__(self):
        return (
            f"Archive for Job #{self.job_id}"
        )