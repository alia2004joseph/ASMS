from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from reports.constants import ClearanceStatus
from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedModel,
    VersionedModel,
)


class FeeClearanceCertificate(
    AbstractGeneratedArtifact,
    VersionedModel,
    SchoolScopedModel,
):
    """
    Official fee clearance certificate.

    IMPORTANT:
    Every monetary value stored here is an immutable snapshot captured from
    the Finance module at the moment the certificate is issued.

    This model NEVER calculates balances itself.
    All calculations belong to reports.services.fee_clearance_service.
    """

    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="fee_clearance_certificates",
    )

    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
        related_name="+",
    )

    term = models.ForeignKey(
        "academics.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="+",
    )

    cleared_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    outstanding_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    clearance_status = models.CharField(
        max_length=30,
        choices=ClearanceStatus.choices,
        db_index=True,
    )

    certificate_number = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )

    verification_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Public verification code used by QR verification.",
    )

    override_reason = models.TextField(
        blank=True,
        default="",
    )

    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_clearance_overrides",
    )

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_fee_clearance_certificates",
    )

    issued_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-issued_at"]

        constraints = [
            models.CheckConstraint(
                condition=Q(cleared_amount__gte=0),
                name="fee_clearance_cleared_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(outstanding_balance__gte=0),
                name="fee_clearance_balance_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(clearance_status=ClearanceStatus.CLEARED_WITH_OVERRIDE)
                    & Q(override_reason__gt="")
                )
                | ~Q(
                    clearance_status=ClearanceStatus.CLEARED_WITH_OVERRIDE
                ),
                name="fee_clearance_override_reason_required",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id", "version"],
                name="unique_fee_clearance_version",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id"],
                condition=Q(is_latest=True),
                name="unique_latest_fee_clearance",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "student", "term"],
                name="fee_clearance_student_term_idx",
            ),
            models.Index(
                fields=["school", "clearance_status"],
                name="fee_clearance_status_idx",
            ),
            models.Index(
                fields=["school", "issued_at"],
                name="fee_clearance_issued_idx",
            ),
            models.Index(
                fields=["root_id", "version"],
                name="fee_clearance_version_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.cleared_amount < 0:
            errors["cleared_amount"] = (
                "Cleared amount cannot be negative."
            )

        if self.outstanding_balance < 0:
            errors["outstanding_balance"] = (
                "Outstanding balance cannot be negative."
            )

        if (
            self.clearance_status
            == ClearanceStatus.CLEARED_WITH_OVERRIDE
        ):
            if not self.override_reason.strip():
                errors["override_reason"] = (
                    "Override reason is required."
                )

            if self.override_by is None:
                errors["override_by"] = (
                    "Override user is required."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.certificate_number} - "
            f"{self.student} "
            f"({self.get_clearance_status_display()})"
        )