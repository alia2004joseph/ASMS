from django.conf import settings
from django.db import models
from django.db.models import Q

from reports.constants import ExportFormat, ReportScope
from reports.models.base import (
    AbstractGeneratedArtifact,
    AuditableModel,
    SchoolScopedModel,
    VersionedModel,
)
from reports.models.report_definitions import ReportType


class GeneratedReport(
    AbstractGeneratedArtifact,
    VersionedModel,
    SchoolScopedModel,
    AuditableModel,
):
    """
    Represents a generated report artifact and its immutable generation inputs.

    The actual generation process must be handled by the Reports service layer
    and background tasks. This model only stores the report's metadata, frozen
    parameters, generated file, lifecycle status, and version history.

    Versioning rules:
    - Every version chain shares one root_id.
    - Version numbers must be unique within a school and chain.
    - Only one version in a chain may have is_latest=True.
    - Regeneration and revocation must go through the versioning service.
    """

    report_type = models.ForeignKey(
        ReportType,
        on_delete=models.PROTECT,
        related_name="generated_reports",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_reports",
        help_text="User who requested the report generation.",
    )

    scope = models.CharField(
        max_length=10,
        choices=ReportScope.choices,
        db_index=True,
    )

    parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Immutable snapshot of the inputs used to generate this report. "
            "May include student, classroom, subject, academic term, date "
            "range, filters, sorting, grouping, aggregates, template version, "
            "and resolved custom-report definitions."
        ),
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="generated_report_version_gte_1",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id", "version"],
                name="unique_generated_report_chain_version",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id"],
                condition=Q(is_latest=True),
                name="unique_latest_generated_report",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "report_type", "-created_at"],
                name="gen_school_type_idx",
            ),
            models.Index(
                fields=["school", "status", "-created_at"],
                name="gen_report_school_status_idx",
            ),
            models.Index(
                fields=["requested_by", "-created_at"],
                name="gen_req_created_idx",
            ),
            models.Index(
                fields=["root_id", "version"],
                name="gen_report_root_version_idx",
            ),
            models.Index(
                fields=["school", "is_latest", "report_type"],
                name="gen_report_latest_type_idx",
            ),
            models.Index(
                fields=["school", "scope", "-created_at"],
                name="gen_report_school_scope_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.report_type.name} "
            f"(v{self.version}) - "
            f"{self.get_status_display()}"
        )


class ReportExportLog(models.Model):
    """
    Immutable audit trail for generated-report download attempts.

    A log should be created by the download service whenever a user attempts
    to access a generated report file. Detailed exceptions should remain in
    application logs; failure_message should contain only a safe explanation.
    """

    generated_report = models.ForeignKey(
        GeneratedReport,
        on_delete=models.PROTECT,
        related_name="export_logs",
    )

    export_format = models.CharField(
        max_length=10,
        choices=ExportFormat.choices,
    )

    downloaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_export_logs",
    )

    downloaded_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    user_agent = models.CharField(
        max_length=512,
        blank=True,
        default="",
    )

    successful = models.BooleanField(
        default=True,
        db_index=True,
    )

    failure_message = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Safe explanation for an unsuccessful download attempt. "
            "Do not store stack traces or sensitive internal information."
        ),
    )

    class Meta:
        ordering = ["-downloaded_at"]

        indexes = [
            models.Index(
                fields=["generated_report", "-downloaded_at"],
                name="report_export_report_time_idx",
            ),
            models.Index(
                fields=["downloaded_by", "-downloaded_at"],
                name="report_export_user_time_idx",
            ),
            models.Index(
                fields=["successful", "-downloaded_at"],
                name="report_export_success_time_idx",
            ),
        ]

    def __str__(self):
        user = (
            str(self.downloaded_by)
            if self.downloaded_by_id
            else "Anonymous/Deleted User"
        )
        result = "successful" if self.successful else "failed"

        return (
            f"{self.generated_report.report_type.name} "
            f"download by {user} ({result})"
        )