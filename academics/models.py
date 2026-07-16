# academics/models.py

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import User


class AcademicYear(models.Model):
    """An academic year belonging to one school."""

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="academic_years",
    )

    name = models.CharField(
        max_length=30,
        help_text="For example: 2026 or 2026/2027.",
    )

    start_date = models.DateField()
    end_date = models.DateField()

    is_active = models.BooleanField(
        default=False,
        help_text="Indicates the current academic year for the school.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_academic_year_name_per_school",
            ),
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(is_active=True),
                name="one_active_academic_year_per_school",
            ),
        ]

    def clean(self):
        errors = {}

        if self.start_date and self.end_date:
            if self.start_date >= self.end_date:
                errors["end_date"] = (
                    "The academic year end date must be after its start date."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} — {self.school.name}"


class AcademicTerm(models.Model):
    """A term belonging to an academic year and school."""

    class TermName(models.TextChoices):
        TERM_ONE = "term_one", "Term One"
        TERM_TWO = "term_two", "Term Two"
        TERM_THREE = "term_three", "Term Three"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="academic_terms",
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="terms",
    )

    name = models.CharField(
        max_length=20,
        choices=TermName.choices,
    )

    start_date = models.DateField()
    end_date = models.DateField()

    is_active = models.BooleanField(
        default=False,
        help_text="Indicates the current academic term for the school.",
    )

    subject_change_deadline = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Students may change elective subjects freely until this date."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["academic_year", "start_date"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "academic_year", "name"],
                name="unique_term_per_academic_year",
            ),
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(is_active=True),
                name="one_active_term_per_school",
            ),
        ]

    def clean(self):
        errors = {}

        if self.academic_year_id and self.school_id:
            if self.academic_year.school_id != self.school_id:
                errors["academic_year"] = (
                    "The academic year must belong to the selected school."
                )

        if self.start_date and self.end_date:
            if self.start_date >= self.end_date:
                errors["end_date"] = (
                    "The academic term end date must be after its start date."
                )

        if self.academic_year_id:
            if (
                self.start_date
                and self.start_date < self.academic_year.start_date
            ):
                errors["start_date"] = (
                    "The term cannot start before the academic year."
                )

            if (
                self.end_date
                and self.end_date > self.academic_year.end_date
            ):
                errors["end_date"] = (
                    "The term cannot end after the academic year."
                )

        if self.subject_change_deadline:
            if self.start_date and self.subject_change_deadline < self.start_date:
                errors["subject_change_deadline"] = (
                    "The subject-change deadline cannot be before the term starts."
                )

            if self.end_date and self.subject_change_deadline > self.end_date:
                errors["subject_change_deadline"] = (
                    "The subject-change deadline cannot be after the term ends."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.get_name_display()} — "
            f"{self.academic_year.name} — {self.school.name}"
        )


class Classroom(models.Model):
    """
    A classroom belonging to one school and academic year.

    This preserves your existing fields and adds academic_year.
    """

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="classrooms",
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="classrooms",
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=100)

    code = models.CharField(max_length=30)

    level = models.CharField(
        max_length=50,
        blank=True,
        help_text="For example: S1, S4, S5 or Year 1.",
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["school", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "code"],
                name="unique_classroom_code_per_school",
            )
        ]

    def clean(self):
        errors = {}

        if self.academic_year_id:
            if self.academic_year.school_id != self.school_id:
                errors["academic_year"] = (
                    "The academic year must belong to the classroom's school."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} — {self.school.name}"


class Subject(models.Model):
    """A subject offered by a specific school."""

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="subjects",
    )

    name = models.CharField(max_length=100)

    code = models.CharField(
        max_length=30,
        help_text="For example: MATH, ENG or PHY.",
    )

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["school", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "code"],
                name="unique_subject_code_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_subject_name_per_school",
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.school.name}"


class ClassroomSubject(models.Model):
    """
    Records a subject taught to a classroom during an academic term.

    A teacher may optionally be assigned to it.
    """

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="classroom_subjects",
    )

    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="classroom_subjects",
    )

    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="classroom_subjects",
    )

    academic_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.CASCADE,
        related_name="classroom_subjects",
    )

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="teaching_assignments",
        null=True,
        blank=True,
        limit_choices_to={"role": User.Role.TEACHER},
    )

    is_compulsory = models.BooleanField(
        default=True,
        help_text=(
            "Compulsory subjects are automatically taken by all students "
            "in the classroom."
        ),
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "classroom",
            "subject",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "classroom",
                    "subject",
                    "academic_term",
                ],
                name="unique_subject_per_classroom_term",
            )
        ]

    def clean(self):
        errors = {}

        if self.classroom_id and self.school_id:
            if self.classroom.school_id != self.school_id:
                errors["classroom"] = (
                    "The classroom must belong to the selected school."
                )

        if self.subject_id and self.school_id:
            if self.subject.school_id != self.school_id:
                errors["subject"] = (
                    "The subject must belong to the selected school."
                )

        if self.academic_term_id and self.school_id:
            if self.academic_term.school_id != self.school_id:
                errors["academic_term"] = (
                    "The academic term must belong to the selected school."
                )

        if self.classroom_id and self.academic_term_id:
            if (
                self.classroom.academic_year_id
                and self.classroom.academic_year_id
                != self.academic_term.academic_year_id
            ):
                errors["academic_term"] = (
                    "The term must belong to the classroom's academic year."
                )

        if self.teacher_id:
            if self.teacher.role != User.Role.TEACHER:
                errors["teacher"] = (
                    "The assigned user must have the teacher role."
                )
            elif not self.teacher.is_active:
                errors["teacher"] = (
                    "The assigned teacher must be active."
                )
            elif self.teacher.approval_status != User.ApprovalStatus.APPROVED:
                errors["teacher"] = (
                    "The assigned teacher must be approved."
                )
            elif self.teacher.school_id != self.school_id:
                errors["teacher"] = (
                    "The assigned teacher must belong to the same school."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.subject.name} — "
            f"{self.classroom.name} — "
            f"{self.academic_term.get_name_display()}"
        )


class StudentEnrollment(models.Model):
    """
    Records that a StudentProfile is taking a ClassroomSubject.

    It links to StudentProfile rather than directly to User.
    """

    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="subject_enrollments",
    )

    classroom_subject = models.ForeignKey(
        ClassroomSubject,
        on_delete=models.CASCADE,
        related_name="student_enrollments",
    )

    enrolled_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = [
            "classroom_subject",
            "student",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "student",
                    "classroom_subject",
                ],
                name="unique_student_classroom_subject_enrollment",
            )
        ]

    def clean(self):
        errors = {}

        if self.student_id and self.classroom_subject_id:
            student_user = self.student.user

            if (
                self.student.school_id
                != self.classroom_subject.school_id
            ):
                errors["classroom_subject"] = (
                    "The student and classroom subject must belong "
                    "to the same school."
                )

            if self.student.classroom_id is None:
                errors["student"] = (
                    "Assign the student to a classroom before enrolling "
                    "them in a subject."
                )
            elif (
                self.student.classroom_id
                != self.classroom_subject.classroom_id
            ):
                errors["classroom_subject"] = (
                    "The classroom subject must belong to the student's "
                    "current classroom."
                )

            if not self.student.is_active_student:
                errors["student"] = (
                    "An inactive student cannot be enrolled."
                )

            if not student_user.is_active:
                errors["student"] = (
                    "The student's user account must be active."
                )
            elif (
                student_user.approval_status
                != User.ApprovalStatus.APPROVED
            ):
                errors["student"] = (
                    "The student's user account must be approved."
                )

            if not self.classroom_subject.is_active:
                errors["classroom_subject"] = (
                    "The classroom subject is not active."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.student.student_id_number} — "
            f"{self.classroom_subject.subject.name}"
        )