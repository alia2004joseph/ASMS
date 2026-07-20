from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from reports.constants import ResultSlipOutcome
from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedModel,
    VersionedModel,
    AuditableModel
)


class ResultSlip(
    AbstractGeneratedArtifact,
    VersionedModel,
    SchoolScopedModel,
    AuditableModel
):
    """
    An official single-term student result document.

    This is intentionally lighter than a full report card.

    `subjects_snapshot` stores the exact subject results used when the slip
    was generated. Later changes to grades must never silently alter an
    already-generated slip. Corrections require creation of a new version
    through the result-slip service.

    Business rules, grade calculations, rankings, and generation logic belong
    in reports.services.result_slip_service.
    """

    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="result_slips",
    )

    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
        related_name="result_slips",
    )

    term = models.ForeignKey(
        "academics.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="result_slips",
    )

    classroom = models.ForeignKey(
        "academics.Classroom",
        on_delete=models.PROTECT,
        related_name="result_slips",
    )

    subjects_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Frozen list of subject results used to generate this slip. "
            "Example: "
            "[{'subject_id': 1, 'subject_name': 'Mathematics', "
            "'subject_code': 'MATH', 'marks': '78.00', "
            "'grade': 'A', 'remarks': 'Excellent'}]."
        ),
    )

    aggregate_or_gpa = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Frozen aggregate, average, or GPA value calculated at generation "
            "time according to the school's grading configuration."
        ),
    )

    position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Frozen student position at generation time. Leave empty where "
            "the school does not publish rankings."
        ),
    )

    class_average = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Frozen class average at generation time.",
    )

    pass_fail_status = models.CharField(
        max_length=20,
        choices=ResultSlipOutcome.choices,
        default=ResultSlipOutcome.NOT_APPLICABLE,
        db_index=True,
    )

    verification_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text=(
            "Public non-sequential code used to verify the authenticity "
            "and current validity of the result slip."
        ),
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(aggregate_or_gpa__isnull=True)
                    | Q(aggregate_or_gpa__gte=Decimal("0.00"))
                ),
                name="rs_aggregate_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(class_average__isnull=True)
                    | Q(class_average__gte=Decimal("0.00"))
                ),
                name="rs_class_avg_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(position__isnull=True) | Q(position__gte=1),
                name="rs_position_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="rs_version_gte_1",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id", "version"],
                name="uniq_rs_chain_version",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id"],
                condition=Q(is_latest=True),
                name="uniq_latest_rs",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "student", "term"],
                name="rs_student_term_idx",
            ),
            models.Index(
                fields=["school", "academic_year", "term"],
                name="rs_year_term_idx",
            ),
            models.Index(
                fields=["school", "classroom", "term"],
                name="rs_class_term_idx",
            ),
            models.Index(
                fields=["school", "pass_fail_status"],
                name="rs_outcome_idx",
            ),
            models.Index(
                fields=["school", "status", "-created_at"],
                name="rs_status_time_idx",
            ),
            models.Index(
                fields=["root_id", "version"],
                name="rs_root_version_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if not isinstance(self.subjects_snapshot, list):
            errors["subjects_snapshot"] = (
                "The subjects snapshot must be a JSON list."
            )
        else:
            for index, subject_result in enumerate(
                self.subjects_snapshot,
                start=1,
            ):
                if not isinstance(subject_result, dict):
                    errors["subjects_snapshot"] = (
                        f"Subject result at position {index} must be "
                        "a JSON object."
                    )
                    break

                if not subject_result.get("subject_name"):
                    errors["subjects_snapshot"] = (
                        f"Subject result at position {index} must include "
                        "'subject_name'."
                    )
                    break

        if (
            self.aggregate_or_gpa is not None
            and self.aggregate_or_gpa < Decimal("0.00")
        ):
            errors["aggregate_or_gpa"] = (
                "Aggregate, average, or GPA cannot be negative."
            )

        if (
            self.class_average is not None
            and self.class_average < Decimal("0.00")
        ):
            errors["class_average"] = (
                "Class average cannot be negative."
            )

        if self.position is not None and self.position < 1:
            errors["position"] = (
                "Student position must be at least 1."
            )

        if (
            self.term_id
            and self.academic_year_id
            and getattr(self.term, "academic_year_id", None)
            != self.academic_year_id
        ):
            errors["term"] = (
                "The selected term does not belong to the selected "
                "academic year."
            )

        if self.school_id:
            student_school_id = getattr(
                self.student,
                "school_id",
                None,
            )
            classroom_school_id = getattr(
                self.classroom,
                "school_id",
                None,
            )
            year_school_id = getattr(
                self.academic_year,
                "school_id",
                None,
            )
            term_school_id = getattr(
                self.term,
                "school_id",
                None,
            )

            if (
                student_school_id is not None
                and student_school_id != self.school_id
            ):
                errors["student"] = (
                    "The student must belong to the result slip's school."
                )

            if (
                classroom_school_id is not None
                and classroom_school_id != self.school_id
            ):
                errors["classroom"] = (
                    "The classroom must belong to the result slip's school."
                )

            if (
                year_school_id is not None
                and year_school_id != self.school_id
            ):
                errors["academic_year"] = (
                    "The academic year must belong to the result slip's "
                    "school."
                )

            if (
                term_school_id is not None
                and term_school_id != self.school_id
            ):
                errors["term"] = (
                    "The term must belong to the result slip's school."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"Result slip: {self.student} — "
            f"{self.term} — v{self.version}"
        )