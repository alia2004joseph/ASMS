"""
Representative assignment models (skeleton).

NOTE: This file defines the ClassRepresentativeAssignment model as a scaffold.
Do NOT run migrations or add this app to INSTALLED_APPS until the design has
been reviewed and you explicitly approve that change. This file is intentionally
non-invasive: it defines the model class but operations that would modify the
database are gated behind migrations which will not be created by this scaffold.
"""

from django.conf import settings
from django.db import models


class ClassRepresentativeAssignment(models.Model):
    """Assignment tying a StudentProfile to a classroom or classroom_subject.

    IMPORTANT: This model file is part of the scaffold. Do not add the app to
    INSTALLED_APPS or create migrations until you explicitly approve doing so.
    """

    # Primary key: default AutoField
    student_profile = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="representative_assignments",
        help_text="StudentProfile that holds the student identity",
    )

    # Either classroom OR classroom_subject may be set
    classroom = models.ForeignKey(
        "academics.Classroom",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    classroom_subject = models.ForeignKey(
        "academics.ClassroomSubject",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    academic_term = models.ForeignKey(
        "academics.AcademicTerm",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_representations",
    )

    assigned_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)

    approval_status = models.CharField(
        max_length=20,
        choices=(
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ),
        default="approved",
    )

    notes = models.TextField(blank=True)

    revoked_at = models.DateTimeField(null=True, blank=True)

    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_representative_assignments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "class_management_representativeassignment"
        verbose_name = "Class Representative Assignment"
        verbose_name_plural = "Class Representative Assignments"
        # Do NOT add unique constraints here yet; enforce in service layer until
        # the model is reviewed and migrations approved.

    def __str__(self):
        target = self.classroom_subject or self.classroom
        return f"Rep: {self.student_profile} -> {target} ({self.academic_term})"
