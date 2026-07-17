# attendance/models.py

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import User
from academics.models import StudentEnrollment
from timetable.models import TimetableEntry


class AttendanceRecord(models.Model):
    """A single student's attendance for one timetable entry on one date."""

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"
        EXCUSED = "excused", "Excused"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name="School",
    )
    timetable_entry = models.ForeignKey(
        TimetableEntry,
        on_delete=models.PROTECT,
        related_name="attendance_records",
        verbose_name="Timetable Entry",
    )
    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name="Student",
    )
    date = models.DateField(verbose_name="Date")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        verbose_name="Status",
    )
    marked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marked_attendance_records",
        verbose_name="Marked By",
    )
    remarks = models.CharField(max_length=255, blank=True, verbose_name="Remarks")
    is_active = models.BooleanField(default=True, verbose_name="Is Active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Attendance Record"
        verbose_name_plural = "Attendance Records"
        ordering = ["-date", "student", "timetable_entry"]
        constraints = [
            models.UniqueConstraint(
    fields=["student", "timetable_entry", "date"],
    condition=models.Q(is_active=True),
    name="unique_active_student_timetable_entry_date",
),
        ]
        indexes = [
    models.Index(fields=["school", "date"]),
    models.Index(fields=["student", "date"]),
    models.Index(fields=["timetable_entry", "date"]),
    models.Index(fields=["marked_by", "date"]),
    models.Index(fields=["school", "status"]),
]
    def __str__(self):
        return (
            f"{self.student} - {self.timetable_entry} - {self.date} "
            f"({self.get_status_display()})"
        )

    def clean(self):
        errors = {}

        if self.remarks:
            self.remarks = self.remarks.strip()

        if self.date and self.date > timezone.localdate():
            errors["date"] = (
                "Attendance cannot be recorded for a future date."
            )

        if self.date and self.timetable_entry_id:
            attendance_weekday = self.date.strftime("%A").lower()

            if attendance_weekday != self.timetable_entry.weekday:
                errors["date"] = (
                    "The attendance date does not match the weekday "
                    "of the selected timetable entry."
                )

        if self.timetable_entry_id and self.school_id:
            if self.timetable_entry.school_id != self.school_id:
                errors["timetable_entry"] = (
                    "The timetable entry must belong to the same school "
                    "as the attendance record."
                )

        if self.student_id and self.school_id:
            if self.student.school_id != self.school_id:
                errors["student"] = (
                    "The student must belong to the same school as the "
                    "attendance record."
                )

        if self.timetable_entry_id:
            timetable_entry = self.timetable_entry

            if not timetable_entry.is_active:
                errors["timetable_entry"] = (
                    "Attendance cannot be created for an inactive "
                    "timetable entry."
                )

            elif not timetable_entry.period.is_active:
                errors["timetable_entry"] = (
                    "Attendance cannot be recorded during an inactive "
                    "period."
                )

            elif timetable_entry.period.is_break:
                errors["timetable_entry"] = (
                    "Attendance cannot be recorded during a break period."
                )

            elif not timetable_entry.classroom_subject.is_active:
                errors["timetable_entry"] = (
                    "Attendance cannot be recorded for an inactive "
                    "classroom subject."
                )

        if self.student_id:
            student_user = self.student.user

            if not self.student.is_active_student:
                errors["student"] = (
                    "Attendance cannot be created for an inactive student."
                )

            elif not student_user.is_active:
                errors["student"] = (
                    "The student's account must be active."
                )

            elif (
                student_user.approval_status
                != User.ApprovalStatus.APPROVED
            ):
                errors["student"] = (
                    "The student's account must be approved."
                )

        if self.marked_by_id:
            marker = self.marked_by

            allowed_roles = {
                User.Role.TEACHER,
                User.Role.ADMIN,
            }

            if not marker.is_superuser and marker.role not in allowed_roles:
                errors["marked_by"] = (
                    "Only a teacher or school administrator may mark "
                    "attendance."
                )

            elif (
                not marker.is_superuser
                and self.school_id
                and marker.school_id != self.school_id
            ):
                errors["marked_by"] = (
                    "The person marking attendance must belong to the "
                    "same school."
                )

            elif (
                self.timetable_entry_id
                and marker.role == User.Role.TEACHER
                and not marker.is_superuser
                and self.timetable_entry.classroom_subject.teacher_id
                != marker.id
            ):
                errors["marked_by"] = (
                    "Teachers may only mark attendance for timetable "
                    "entries assigned to them."
                )

        if self.timetable_entry_id and self.student_id:
            enrolled = StudentEnrollment.objects.filter(
                student=self.student,
                classroom_subject=(
                    self.timetable_entry.classroom_subject
                ),
            ).exists()

            if not enrolled:
                errors["student"] = (
                    "The student is not enrolled in this classroom "
                    "subject."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)