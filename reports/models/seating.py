from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from reports.constants import (
    InvigilatorRole,
    SeatAssignmentStatus,
)
from reports.models.base import AuditableModel, SchoolScopedModel


class SeatingPlan(SchoolScopedModel, AuditableModel):
    """
    Represents the seating arrangement for one examination session and room.

    `external_reference` is intentionally stored as structured JSON until a
    dedicated Examinations application exists.

    Example:

        {
            "exam_session_id": 42,
            "exam_id": 12,
            "source": "examinations"
        }

    The Reports module must never interpret values from this field as raw ORM
    paths. Integration with a future Examinations module belongs in a service.
    """

    external_reference = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured reference to an external examination session. "
            "Example: {'exam_session_id': 42}."
        ),
    )

    room = models.CharField(
        max_length=100,
    )

    exam_date = models.DateField(
        db_index=True,
    )

    start_time = models.TimeField()

    end_time = models.TimeField()

    capacity = models.PositiveIntegerField(
        help_text="Maximum number of candidates permitted in this room.",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = ["exam_date", "start_time", "room"]

        constraints = [
            models.CheckConstraint(
                condition=Q(capacity__gte=1),
                name="seating_plan_capacity_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="seating_plan_end_after_start",
            ),
            models.UniqueConstraint(
                fields=[
                    "school",
                    "room",
                    "exam_date",
                    "start_time",
                ],
                name="unique_room_exam_session",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "exam_date", "room"],
                name="seating_school_date_idx",
            ),
            models.Index(
                fields=["school", "exam_date", "is_active"],
                name="seating_plan_school_active_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.capacity is not None and self.capacity < 1:
            errors["capacity"] = "Room capacity must be at least 1."

        if (
            self.start_time
            and self.end_time
            and self.end_time <= self.start_time
        ):
            errors["end_time"] = (
                "The examination end time must be later than the start time."
            )

        if not isinstance(self.external_reference, dict):
            errors["external_reference"] = (
                "External reference must be a JSON object."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.room} — {self.exam_date} "
            f"{self.start_time:%H:%M}"
        )


class SeatAssignment(models.Model):
    """
    Assigns one student to one seat within a seating plan.

    Seat allocation and room-capacity enforcement must be handled by the
    seating-plan service inside a transaction. The database constraints
    protect against duplicate seats and duplicate candidates.
    """

    seating_plan = models.ForeignKey(
        SeatingPlan,
        on_delete=models.CASCADE,
        related_name="seat_assignments",
    )

    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="exam_seat_assignments",
    )

    seat_number = models.CharField(
        max_length=20,
    )

    subject_or_paper = models.CharField(
        max_length=150,
        help_text="Frozen subject or examination-paper label.",
    )

    special_needs_accommodation = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Approved examination accommodation, such as accessible seating "
            "or additional space."
        ),
    )

    status = models.CharField(
        max_length=25,
        choices=SeatAssignmentStatus.choices,
        default=SeatAssignmentStatus.ASSIGNED,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["seat_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["seating_plan", "seat_number"],
                name="unique_seat_per_plan",
            ),
            models.UniqueConstraint(
                fields=["seating_plan", "student"],
                name="unique_student_per_seating_plan",
            ),
        ]

        indexes = [
            models.Index(
                fields=["seating_plan", "status"],
                name="seat_plan_status_idx",
            ),
            models.Index(
                fields=["seating_plan", "student"],
                name="seat_plan_student_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if not self.seat_number or not self.seat_number.strip():
            errors["seat_number"] = "Seat number is required."

        if self.seating_plan_id and self.student_id:
            plan_school_id = self.seating_plan.school_id
            student_school_id = getattr(self.student, "school_id", None)

            if (
                student_school_id is not None
                and student_school_id != plan_school_id
            ):
                errors["student"] = (
                    "The student must belong to the same school as the "
                    "seating plan."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.student} — Seat {self.seat_number} "
            f"({self.seating_plan})"
        )


class InvigilatorAssignment(models.Model):
    """
    Assigns a staff user to invigilate an examination seating plan.

    Only one active chief invigilator may be assigned to a seating plan.
    Staff-role eligibility and school membership must also be checked by the
    invigilation service before creating an assignment.
    """

    seating_plan = models.ForeignKey(
        SeatingPlan,
        on_delete=models.CASCADE,
        related_name="invigilator_assignments",
    )

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="exam_invigilation_assignments",
    )

    role = models.CharField(
        max_length=10,
        choices=InvigilatorRole.choices,
        default=InvigilatorRole.ASSISTANT,
        db_index=True,
    )

    assigned_at = models.DateTimeField(
        auto_now_add=True,
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = ["role", "assigned_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["seating_plan", "staff"],
                condition=Q(is_active=True),
                name="unique_active_invigilator_per_plan",
            ),
            models.UniqueConstraint(
                fields=["seating_plan"],
                condition=Q(
                    role=InvigilatorRole.CHIEF,
                    is_active=True,
                ),
                name="unique_active_chief_invigilator",
            ),
        ]

        indexes = [
            models.Index(
                fields=["seating_plan", "role"],
                name="invigilator_plan_role_idx",
            ),
            models.Index(
                fields=["staff", "is_active"],
                name="invigilator_staff_active_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.seating_plan_id and self.staff_id:
            plan_school_id = self.seating_plan.school_id
            staff_school_id = getattr(self.staff, "school_id", None)

            if (
                staff_school_id is not None
                and staff_school_id != plan_school_id
            ):
                errors["staff"] = (
                    "The invigilator must belong to the same school as the "
                    "seating plan."
                )

            if not getattr(self.staff, "is_active", True):
                errors["staff"] = (
                    "An inactive user cannot be assigned as an invigilator."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.staff} — {self.get_role_display()} "
            f"({self.seating_plan})"
        )