"""
Shared abstract models for the Reports & Analytics module.

Integration requirements:
- settings.AUTH_USER_MODEL must resolve to the ASMS user model.
- settings.ASMS_SCHOOL_MODEL may override the default schools.School model.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from reports.constants import (
    ExportFormat,
    GeneratedReportStatus,
)


SCHOOL_MODEL = getattr(
    settings,
    "ASMS_SCHOOL_MODEL",
    "schools.School",
)


class SchoolScopedQuerySet(models.QuerySet):
    def for_school(self, school):
        if school is None:
            raise ValueError(
                "for_school() requires a concrete school."
            )

        return self.filter(school=school)


class SchoolScopedManager(
    models.Manager.from_queryset(SchoolScopedQuerySet)
):
    pass


class SchoolScopedModel(models.Model):
    school = models.ForeignKey(
        SCHOOL_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )

    objects = SchoolScopedManager()

    class Meta:
        abstract = True


class AuditableModel(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VersionedModel(models.Model):
    """
    Shared version-chain metadata.

    `root_id` is a stable UUID shared by all records in one version chain.
    The first version receives a new UUID. Regenerated versions copy the
    same root_id through the versioning service.
    """

    root_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )
    version = models.PositiveIntegerField(default=1)

    previous_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    is_latest = models.BooleanField(
        default=True,
        db_index=True,
    )

    regeneration_reason = models.TextField(
        blank=True,
        default="",
    )

    is_revoked = models.BooleanField(
        default=False,
        db_index=True,
    )
    revoked_reason = models.TextField(
        blank=True,
        default="",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    def clean(self):
        super().clean()

        errors = {}

        if self.is_revoked:
            if not self.revoked_reason.strip():
                errors["revoked_reason"] = (
                    "A revocation reason is required."
                )

            if self.revoked_at is None or self.revoked_by_id is None:
                errors["is_revoked"] = (
                    "Use the official revocation workflow so that the "
                    "revocation time and revoking user are recorded automatically."
                )

        else:
            if self.revoked_reason:
                errors["revoked_reason"] = (
                    "A non-revoked document cannot have a revocation reason."
                )

            if self.revoked_at is not None:
                errors["is_revoked"] = (
                    "A non-revoked document cannot have a revocation timestamp."
                )

            if self.revoked_by_id is not None:
                errors["is_revoked"] = (
                    "A non-revoked document cannot have a revoking user."
                )

        if errors:
            raise ValidationError(errors)
    class Meta:
        abstract = True


def _generated_file_upload_path(instance, filename):
    document_type = str(
        getattr(
            instance,
            "document_type",
            instance.__class__.__name__,
        )
    ).lower()

    school_id = getattr(instance, "school_id", "unscoped")
    extension = Path(filename).suffix.lower()

    return (
        f"reports/{school_id}/{document_type}/"
        f"{uuid.uuid4().hex}{extension}"
    )


class AbstractGeneratedArtifact(models.Model):
    file = models.FileField(
        upload_to=_generated_file_upload_path,
        null=True,
        blank=True,
    )

    file_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
    )

    file_size = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )

    mime_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    export_format = models.CharField(
        max_length=10,
        choices=ExportFormat.choices,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=GeneratedReportStatus.choices,
        default=GeneratedReportStatus.PENDING,
        db_index=True,
    )

    failure_message = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        abstract = True