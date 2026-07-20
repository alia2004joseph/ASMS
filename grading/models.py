# grading/models.py
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from schools.models import School
from academics.models import ClassroomSubject, StudentEnrollment
from accounts.models import User
from decimal import Decimal, ROUND_HALF_UP


class AssessmentType(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="assessment_types")
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    weight_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="uniq_assessmenttype_school_name"),
            models.UniqueConstraint(fields=["school", "code"], name="uniq_assessmenttype_school_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.school})"

    def clean(self):
        if self.weight_percentage is None or self.weight_percentage <= 0 or self.weight_percentage > 100:
            raise ValidationError({"weight_percentage": "Weight percentage must be > 0 and <= 100."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class Assessment(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="assessments",
    )

    classroom_subject = models.ForeignKey(
        ClassroomSubject,
        on_delete=models.CASCADE,
        related_name="assessments",
    )

    assessment_type = models.ForeignKey(
        AssessmentType,
        on_delete=models.PROTECT,
        related_name="assessments",
    )

    title = models.CharField(
        max_length=100,
        help_text="For example: Test 1, Test 2, Midterm Exam.",
    )

    maximum_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )

    assessment_date = models.DateField()

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["assessment_date", "title"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "classroom_subject",
                    "title",
                ],
                name="uniq_assessment_title_per_classroom_subject",
            )
        ]

    def clean(self):
        errors = {}

        if self.maximum_score is None or self.maximum_score <= 0:
            errors["maximum_score"] = (
                "Maximum score must be greater than zero."
            )

        if (
            self.classroom_subject_id
            and self.classroom_subject.school_id != self.school_id
        ):
            errors["classroom_subject"] = (
                "Classroom subject must belong to the same school."
            )

        if (
            self.assessment_type_id
            and self.assessment_type.school_id != self.school_id
        ):
            errors["assessment_type"] = (
                "Assessment type must belong to the same school."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.title} — "
            f"{self.classroom_subject.subject.name}"
        )

class GradeStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Grade(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="grades",
    )

    student_enrollment = models.ForeignKey(
        StudentEnrollment,
        on_delete=models.CASCADE,
        related_name="grades",
    )

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="grades",
    )

    score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )

    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        editable=False,
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_grades",
    )

    remarks = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=GradeStatus.choices,
        default=GradeStatus.DRAFT,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student_enrollment", "assessment"],
                name="uniq_grade_enrollment_assessment",
            )
        ]
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return (
            f"{self.student_enrollment} - "
            f"{self.assessment.title} - "
            f"{self.score}/{self.assessment.maximum_score}"
        )

    def clean(self):
        errors = {}

        if self.score is None or self.score < 0:
            errors["score"] = "Score cannot be negative."

        maximum_score = (
            self.assessment.maximum_score
            if self.assessment_id
            else None
        )

        if (
            self.score is not None
            and maximum_score is not None
            and self.score > maximum_score
        ):
            errors["score"] = (
                "Score cannot exceed the assessment maximum score."
            )

        if (
            self.student_enrollment_id
            and self.student_enrollment.classroom_subject.school_id
            != self.school_id
        ):
            errors["student_enrollment"] = (
                "Student enrollment does not belong to this school."
            )

        if (
            self.assessment_id
            and self.assessment.school_id != self.school_id
        ):
            errors["assessment"] = (
                "Assessment does not belong to this school."
            )

        if self.student_enrollment_id and self.assessment_id:
            if (
                self.student_enrollment.classroom_subject_id
                != self.assessment.classroom_subject_id
            ):
                errors["assessment"] = (
                    "The assessment must belong to the same classroom "
                    "subject as the student enrollment."
                )

        if self.recorded_by_id:
            teacher = self.recorded_by

            classroom_subject = (
                self.student_enrollment.classroom_subject
                if self.student_enrollment_id
                else None
            )

            if teacher.role != User.Role.TEACHER:
                errors["recorded_by"] = (
                    "Only a teacher may record a grade."
                )
            elif not teacher.is_active:
                errors["recorded_by"] = (
                    "The teacher account must be active."
                )
            elif (
                teacher.approval_status
                != User.ApprovalStatus.APPROVED
            ):
                errors["recorded_by"] = (
                    "The teacher account must be approved."
                )
            elif teacher.school_id != self.school_id:
                errors["recorded_by"] = (
                    "The teacher must belong to the same school."
                )
            elif (
                classroom_subject
                and classroom_subject.teacher_id != teacher.id
            ):
                errors["recorded_by"] = (
                    "The teacher is not assigned to this classroom subject."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        maximum_score = (
            self.assessment.maximum_score
            if self.assessment_id
            else None
        )

        if (
            self.score is not None
            and maximum_score is not None
            and maximum_score > 0
        ):
            self.percentage = (
                (self.score / maximum_score) * Decimal("100")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        self.full_clean()
        super().save(*args, **kwargs)

class GradeHistory(models.Model):
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name="history")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="grade_history_changes"
    )
    old_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    new_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    old_status = models.CharField(max_length=20, choices=GradeStatus.choices, null=True, blank=True)
    new_status = models.CharField(max_length=20, choices=GradeStatus.choices, null=True, blank=True)
    reason = models.TextField(blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"History for Grade #{self.grade_id} at {self.changed_at}"

    def delete(self, *args, **kwargs):
        # Append-only: block deletion at the model layer.
        raise ValidationError("GradeHistory records cannot be deleted.")


class SubjectApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class SubjectGradeApproval(models.Model):
    """
    Recommended workflow:
    - Teacher submits grades individually (Grade.status -> submitted).
    - Teacher (or system) creates/updates a SubjectGradeApproval as 'pending'
      once all grades for the ClassroomSubject/term are submitted.
    - School admin reviews and approves/rejects the SubjectGradeApproval.
    - On approval, all 'submitted' grades for that ClassroomSubject move to
      'approved' in one atomic transaction; on rejection they move to 'rejected'.
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subject_grade_approvals")
    classroom_subject = models.OneToOneField(
        ClassroomSubject, on_delete=models.CASCADE, related_name="grade_approval"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grade_approvals_reviewed",
    )
    status = models.CharField(
        max_length=20, choices=SubjectApprovalStatus.choices, default=SubjectApprovalStatus.PENDING
    )
    remarks = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Approval for {self.classroom_subject} - {self.status}"

    def clean(self):
        if self.classroom_subject and self.classroom_subject.school_id != self.school_id:
            raise ValidationError({"classroom_subject": "Classroom subject does not belong to this school."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @transaction.atomic
    def apply_decision(self, new_status, actor, remarks=""):
        if self.status != SubjectApprovalStatus.PENDING:
            raise ValidationError(
                "This grade submission has already been reviewed."
            )

        if new_status not in {
            SubjectApprovalStatus.APPROVED,
            SubjectApprovalStatus.REJECTED,
        }:
            raise ValidationError(
                "The decision must be approved or rejected."
            )

        if not actor or not actor.is_authenticated:
            raise ValidationError(
                "An authenticated administrator is required."
            )

        if not actor.is_superuser:
            if (
                actor.role != User.Role.ADMIN
                or not actor.is_active
                or actor.approval_status
                != User.ApprovalStatus.APPROVED
                or actor.school_id != self.school_id
            ):
                raise ValidationError(
                    "Only an approved administrator from this school "
                    "may review grade submissions."
                )

        if (
            new_status == SubjectApprovalStatus.REJECTED
            and not remarks.strip()
        ):
            raise ValidationError(
                "A rejection reason is required."
            )

        grades = Grade.objects.select_for_update().filter(
            school=self.school,
            student_enrollment__classroom_subject=self.classroom_subject,
            status=GradeStatus.SUBMITTED,
        )

        if not grades.exists():
            raise ValidationError(
                "There are no submitted grades to review."
            
            )

        
        target_status = (
            GradeStatus.APPROVED
            if new_status == SubjectApprovalStatus.APPROVED
            else GradeStatus.REJECTED
        )

        self.status = new_status
        self.approved_by = actor
        self.remarks = remarks.strip()
        self.approved_at = timezone.now()
        self.save()

        for grade in grades:
            old_status = grade.status
            grade.status = target_status
            grade.save(update_fields=["status", "updated_at"])

            GradeHistory.objects.create(
                grade=grade,
                changed_by=actor,
                old_score=grade.score,
                new_score=grade.score,
                old_status=old_status,
                new_status=target_status,
                reason=(
                    "Subject grade submission approved."
                    if new_status == SubjectApprovalStatus.APPROVED
                    else remarks.strip()
                ),
            )