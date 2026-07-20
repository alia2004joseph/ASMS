from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from reports.constants import PerformanceSnapshotSource
from reports.models.base import SchoolScopedModel


class PerformanceSnapshot(SchoolScopedModel):
    """
    Stores an immutable snapshot of a student's official academic performance
    for a particular academic term.

    Snapshots are created only when:

    - an official report card is issued;
    - an official result slip is issued;
    - a transcript requires frozen historical performance;
    - a scheduled analytics job captures term performance; or
    - an authorized administrator explicitly creates a snapshot.

    Ordinary dashboard queries must calculate current performance directly
    from the Grading and Academics modules.

    This model exists so previously issued documents and historical trend
    charts do not change when:

    - grades are corrected;
    - grading rules change;
    - subject combinations change;
    - classroom assignments change; or
    - position-calculation rules are updated.

    Creation and retrieval must be handled through the performance snapshot
    service. Existing snapshots must not be modified in place.
    """

    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="performance_snapshots",
    )

    academic_term = models.ForeignKey(
        "academics.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="performance_snapshots",
    )

    snapshot_source = models.CharField(
        max_length=30,
        choices=PerformanceSnapshotSource.choices,
        db_index=True,
        help_text="The process or official document that caused this snapshot to be created.",
    )

    grading_policy_version = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Identifier of the grading policy or grading configuration used "
            "when the snapshot was calculated."
        ),
    )

    gpa = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Frozen GPA calculated for this academic term.",
    )

    aggregate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Frozen aggregate score calculated for this academic term.",
    )

    class_position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Student's frozen position within the classroom or cohort.",
    )

    class_size = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of ranked students when class_position was calculated.",
    )

    subject_positions = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Frozen mapping of subject codes to positions. "
            "Example: {'MATH': 1, 'ENG': 4, 'PHY': 2}."
        ),
    )

    class_average = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Frozen average performance of the student's classroom or cohort.",
    )

    school_average = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Frozen school-wide average for the corresponding academic context.",
    )

    performance_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Additional frozen performance statistics used by reports and "
            "analytics. This must contain a JSON object."
        ),
    )

    computed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="computed_performance_snapshots",
        help_text=(
            "User responsible for creating the snapshot. This may be empty "
            "for fully automated scheduled jobs."
        ),
    )

    computation_reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Optional idempotency or job reference used to prevent the same "
            "snapshot-generation operation from being processed twice."
        ),
    )

    computed_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "-computed_at",
            "-id",
        ]

        constraints = [
            models.CheckConstraint(
                condition=Q(gpa__isnull=True) | Q(gpa__gte=0),
                name="performance_snapshot_gpa_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(aggregate__isnull=True) | Q(aggregate__gte=0),
                name="performance_snapshot_aggregate_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(class_average__isnull=True)
                    | Q(class_average__gte=0)
                ),
                name="performance_snapshot_class_average_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(school_average__isnull=True)
                    | Q(school_average__gte=0)
                ),
                name="performance_snapshot_school_average_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(class_position__isnull=True)
                    | Q(class_position__gte=1)
                ),
                name="performance_snapshot_position_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(class_size__isnull=True)
                    | Q(class_size__gte=1)
                ),
                name="performance_snapshot_class_size_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(class_position__isnull=True)
                    | Q(class_size__isnull=True)
                    | Q(class_position__lte=models.F("class_size"))
                ),
                name="performance_snapshot_position_within_class",
            ),
            models.UniqueConstraint(
                fields=[
                    "school",
                    "student",
                    "academic_term",
                    "snapshot_source",
                ],
                name="unique_student_term_snapshot_source",
            ),
            models.UniqueConstraint(
                fields=[
                    "school",
                    "computation_reference",
                ],
                condition=~Q(computation_reference=""),
                name="unique_performance_computation_reference",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "school",
                    "student",
                    "academic_term",
                ],
                name="perf_school_stu_term_idx",
            ),
            models.Index(
                fields=[
                    "school",
                    "academic_term",
                    "snapshot_source",
                ],
                name="perf_school_term_src_idx",
            ),
            models.Index(
                fields=[
                    "student",
                    "-computed_at",
                ],
                name=" perf_student_hist_idx",
            ),
            models.Index(
                fields=[
                    "school",
                    "snapshot_source",
                    "-computed_at",
                ],
                name="performance_source_date_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.student_id and self.school_id:
            student_school_id = getattr(self.student, "school_id", None)

            if (
                student_school_id is not None
                and student_school_id != self.school_id
            ):
                errors["student"] = (
                    "The student must belong to the same school as the "
                    "performance snapshot."
                )

        if self.academic_term_id and self.school_id:
            term_school_id = getattr(self.academic_term, "school_id", None)

            if (
                term_school_id is not None
                and term_school_id != self.school_id
            ):
                errors["academic_term"] = (
                    "The academic term must belong to the same school as the "
                    "performance snapshot."
                )

        if self.gpa is not None and self.gpa < 0:
            errors["gpa"] = "GPA cannot be negative."

        if self.aggregate is not None and self.aggregate < 0:
            errors["aggregate"] = "Aggregate cannot be negative."

        if self.class_average is not None and self.class_average < 0:
            errors["class_average"] = "Class average cannot be negative."

        if self.school_average is not None and self.school_average < 0:
            errors["school_average"] = "School average cannot be negative."

        if self.class_position is not None and self.class_position < 1:
            errors["class_position"] = "Class position must be at least 1."

        if self.class_size is not None and self.class_size < 1:
            errors["class_size"] = "Class size must be at least 1."

        if (
            self.class_position is not None
            and self.class_size is not None
            and self.class_position > self.class_size
        ):
            errors["class_position"] = (
                "Class position cannot be greater than class size."
            )

        if not isinstance(self.subject_positions, dict):
            errors["subject_positions"] = (
                "Subject positions must be stored as a JSON object."
            )
        else:
            invalid_subject_positions = {}

            for subject_code, position in self.subject_positions.items():
                if not isinstance(subject_code, str) or not subject_code.strip():
                    invalid_subject_positions[str(subject_code)] = (
                        "Subject code must be a non-empty string."
                    )
                    continue

                if (
                    isinstance(position, bool)
                    or not isinstance(position, int)
                    or position < 1
                ):
                    invalid_subject_positions[subject_code] = (
                        "Subject position must be a positive integer."
                    )

            if invalid_subject_positions:
                errors["subject_positions"] = (
                    "Invalid subject positions: "
                    f"{invalid_subject_positions}"
                )

        if not isinstance(self.performance_summary, dict):
            errors["performance_summary"] = (
                "Performance summary must be stored as a JSON object."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        Prevent modifications to an existing snapshot.

        Performance snapshots are historical records. Corrections must be
        represented by creating a new snapshot through the service layer,
        rather than changing the existing record.
        """

        if self.pk:
            raise ValidationError(
                "Performance snapshots are immutable and cannot be modified."
            )

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Prevent normal deletion of historical performance snapshots.

        Exceptional removals, such as legally approved data correction or
        test-data cleanup, must use a controlled administrative service.
        """

        raise ValidationError(
            "Performance snapshots are historical records and cannot be deleted."
        )

    def __str__(self):
        return (
            f"{self.student} — {self.academic_term} — "
            f"{self.get_snapshot_source_display()}"
        )