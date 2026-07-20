from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedModel,
    VersionedModel,
)


class TranscriptRecord(
    AbstractGeneratedArtifact,
    VersionedModel,
    SchoolScopedModel,
):
    """
    Represents one generated version of a student's academic transcript.

    An official transcript is an immutable legal academic document. Its
    calculated figures must be frozen in TranscriptGPASnapshot rows when the
    transcript is generated.

    If grades, credits, grading policies, or academic records change later,
    the existing transcript must not be edited. A new TranscriptRecord version
    must instead be created with a regeneration reason.

    `cumulative_gpa` and `credits_earned_total` are cached summary values.
    They must always be derived from the related GPA snapshots by the
    transcript-generation service and must never be independently entered.
    """

    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="transcripts",
    )

    is_official = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Official transcripts are issued academic records. Unofficial "
            "transcripts are informational copies."
        ),
    )

    verification_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text=(
            "Public, non-sequential code used to verify this exact transcript "
            "version."
        ),
    )

    cumulative_gpa = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text=(
            "Cached cumulative GPA derived from the transcript GPA snapshots."
        ),
    )

    credits_earned_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Cached total credits earned, derived from the transcript GPA "
            "snapshots."
        ),
    )

    student_name_snapshot = models.CharField(
        max_length=200,
        help_text=(
            "Frozen student name displayed on this transcript version."
        ),
    )

    identification_number_snapshot = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Frozen student registration, admission, or identification number."
        ),
    )

    programme_snapshot = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "Frozen programme, course, or academic pathway displayed on the "
            "transcript."
        ),
    )

    grading_policy_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Frozen grading-policy information used when this transcript was "
            "calculated."
        ),
    )

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_transcripts",
    )

    issued_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "-issued_at",
            "-created_at",
        ]

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(cumulative_gpa__isnull=True)
                    | Q(cumulative_gpa__gte=0)
                ),
                name="transcript_cumulative_gpa_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(credits_earned_total__isnull=True)
                    | Q(credits_earned_total__gte=0)
                ),
                name="transcript_credits_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="transcript_version_gte_1",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_official=False)
                    | Q(issued_at__isnull=False)
                ),
                name="official_transcript_requires_issue_date",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id", "version"],
                name="unique_transcript_chain_version",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id"],
                condition=Q(is_latest=True),
                name="unique_latest_transcript_version",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "student", "is_official"],
                name="tr_school_stu_type_idx",
            ),
            models.Index(
                fields=["school", "is_official", "-issued_at"],
                name="transcript_school_issue_idx",
            ),
            models.Index(
                fields=["student", "-issued_at"],
                name="transcript_student_history_idx",
            ),
            models.Index(
                fields=["root_id", "version"],
                name="transcript_root_version_idx",
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
                    "transcript."
                )

        if self.issued_by_id and self.school_id:
            issuer_school_id = getattr(self.issued_by, "school_id", None)

            if (
                issuer_school_id is not None
                and issuer_school_id != self.school_id
                and not getattr(self.issued_by, "is_superuser", False)
            ):
                errors["issued_by"] = (
                    "The issuing user must belong to the same school as the "
                    "transcript."
                )

            if not getattr(self.issued_by, "is_active", True):
                errors["issued_by"] = (
                    "An inactive user cannot issue a transcript."
                )

        if self.is_official and self.issued_at is None:
            errors["issued_at"] = (
                "An official transcript must have an issue date."
            )

        if self.cumulative_gpa is not None and self.cumulative_gpa < 0:
            errors["cumulative_gpa"] = (
                "Cumulative GPA cannot be negative."
            )

        if (
            self.credits_earned_total is not None
            and self.credits_earned_total < 0
        ):
            errors["credits_earned_total"] = (
                "Total credits earned cannot be negative."
            )

        if not self.student_name_snapshot.strip():
            errors["student_name_snapshot"] = (
                "A frozen student name is required."
            )

        if not isinstance(self.grading_policy_snapshot, dict):
            errors["grading_policy_snapshot"] = (
                "Grading policy snapshot must be stored as a JSON object."
            )

        if (
            self.previous_version_id
            and self.previous_version_id == self.pk
        ):
            errors["previous_version"] = (
                "A transcript cannot reference itself as its previous version."
            )

        if self.previous_version_id:
            previous = self.previous_version

            if previous.school_id != self.school_id:
                errors["previous_version"] = (
                    "The previous transcript version must belong to the same "
                    "school."
                )
            elif previous.student_id != self.student_id:
                errors["previous_version"] = (
                    "The previous transcript version must belong to the same "
                    "student."
                )
            elif previous.root_id != self.root_id:
                errors["previous_version"] = (
                    "The previous transcript version must belong to the same "
                    "version chain."
                )
            elif previous.version >= self.version:
                errors["previous_version"] = (
                    "The previous transcript must have a lower version number."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        transcript_kind = "Official" if self.is_official else "Unofficial"

        return (
            f"{transcript_kind} transcript — "
            f"{self.student_name_snapshot} — v{self.version}"
        )


class TranscriptGPASnapshot(models.Model):
    """
    Stores one immutable academic-period summary represented on a transcript.

    These rows are created by the transcript-generation service and are never
    edited afterward. A corrected transcript must create a new TranscriptRecord
    version and a new collection of snapshot rows.

    Snapshot labels are stored alongside the AcademicTerm foreign key so that
    an already-issued transcript remains historically understandable even if
    academic-term names are later changed.
    """

    transcript = models.ForeignKey(
        TranscriptRecord,
        on_delete=models.CASCADE,
        related_name="gpa_snapshots",
    )

    academic_term = models.ForeignKey(
        "academics.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="transcript_gpa_snapshots",
    )

    sequence_number = models.PositiveIntegerField(
        help_text=(
            "Display order of this academic period within the transcript."
        ),
    )

    academic_year_snapshot = models.CharField(
        max_length=100,
        help_text="Frozen academic-year label displayed on the transcript.",
    )

    term_name_snapshot = models.CharField(
        max_length=100,
        help_text="Frozen academic-term label displayed on the transcript.",
    )

    term_gpa = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text=(
            "Frozen GPA for this academic term. It may be empty where the "
            "school does not use GPA."
        ),
    )

    cumulative_gpa = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text=(
            "Frozen cumulative GPA at the end of this academic term."
        ),
    )

    credits_attempted = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    credits_earned = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    term_aggregate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Optional frozen aggregate for schools that use aggregate-based "
            "grading instead of GPA."
        ),
    )

    results_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Frozen subject-level transcript entries for this term. Each item "
            "should contain fields such as subject code, subject name, grade, "
            "score, credits and remarks."
        ),
    )

    computed_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = [
            "sequence_number",
            "id",
        ]

        constraints = [
            models.CheckConstraint(
                condition=Q(sequence_number__gte=1),
                name="transcript_snapshot_sequence_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(term_gpa__isnull=True) | Q(term_gpa__gte=0),
                name="transcript_snapshot_term_gpa_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(cumulative_gpa__isnull=True)
                    | Q(cumulative_gpa__gte=0)
                ),
                name="transcript_snapshot_cumulative_gpa_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(credits_attempted__gte=0),
                name="transcript_snapshot_attempted_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(credits_earned__gte=0),
                name="transcript_snapshot_earned_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(credits_earned__lte=F("credits_attempted")),
                name="transcript_snapshot_earned_lte_attempted",
            ),
            models.CheckConstraint(
                condition=(
                    Q(term_aggregate__isnull=True)
                    | Q(term_aggregate__gte=0)
                ),
                name="transcript_snapshot_aggregate_nonnegative",
            ),
            models.UniqueConstraint(
                fields=["transcript", "academic_term"],
                name="unique_term_per_transcript",
            ),
            models.UniqueConstraint(
                fields=["transcript", "sequence_number"],
                name="unique_transcript_snapshot_sequence",
            ),
        ]

        indexes = [
            models.Index(
                fields=["transcript", "academic_term"],
                name="transcript_snapshot_term_idx",
            ),
            models.Index(
                fields=["transcript", "sequence_number"],
                name="transcript_snapshot_order_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.sequence_number is not None and self.sequence_number < 1:
            errors["sequence_number"] = (
                "Sequence number must be at least 1."
            )

        if self.term_gpa is not None and self.term_gpa < 0:
            errors["term_gpa"] = "Term GPA cannot be negative."

        if self.cumulative_gpa is not None and self.cumulative_gpa < 0:
            errors["cumulative_gpa"] = (
                "Cumulative GPA cannot be negative."
            )

        if self.credits_attempted is not None and self.credits_attempted < 0:
            errors["credits_attempted"] = (
                "Credits attempted cannot be negative."
            )

        if self.credits_earned is not None and self.credits_earned < 0:
            errors["credits_earned"] = (
                "Credits earned cannot be negative."
            )

        if (
            self.credits_attempted is not None
            and self.credits_earned is not None
            and self.credits_earned > self.credits_attempted
        ):
            errors["credits_earned"] = (
                "Credits earned cannot exceed credits attempted."
            )

        if self.term_aggregate is not None and self.term_aggregate < 0:
            errors["term_aggregate"] = (
                "Term aggregate cannot be negative."
            )

        if not self.academic_year_snapshot.strip():
            errors["academic_year_snapshot"] = (
                "A frozen academic-year label is required."
            )

        if not self.term_name_snapshot.strip():
            errors["term_name_snapshot"] = (
                "A frozen academic-term label is required."
            )

        if not isinstance(self.results_snapshot, list):
            errors["results_snapshot"] = (
                "Results snapshot must be stored as a JSON list."
            )
        else:
            invalid_rows = []

            for index, result in enumerate(self.results_snapshot):
                if not isinstance(result, dict):
                    invalid_rows.append(
                        f"Item {index + 1} must be a JSON object."
                    )
                    continue

                subject_code = result.get("subject_code")
                subject_name = result.get("subject_name")

                if not subject_code and not subject_name:
                    invalid_rows.append(
                        f"Item {index + 1} must contain subject_code or "
                        "subject_name."
                    )

            if invalid_rows:
                errors["results_snapshot"] = invalid_rows

        if self.transcript_id and self.academic_term_id:
            transcript_school_id = self.transcript.school_id
            term_school_id = getattr(
                self.academic_term,
                "school_id",
                None,
            )

            if (
                term_school_id is not None
                and term_school_id != transcript_school_id
            ):
                errors["academic_term"] = (
                    "The academic term must belong to the same school as the "
                    "transcript."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "Transcript GPA snapshots are immutable and cannot be modified."
            )

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Transcript GPA snapshots cannot be deleted independently."
        )

    def __str__(self):
        return (
            f"{self.transcript} — "
            f"{self.academic_year_snapshot} "
            f"{self.term_name_snapshot}"
        )