# timetable/models.py

from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import User
from academics.models import ClassroomSubject


class Period(models.Model):
    """A named teaching period or break belonging to a school."""

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="periods",
    )
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    order = models.PositiveIntegerField()
    is_break = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["school", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_period_name_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "order"],
                name="unique_period_order_per_school",
            ),
        ]

    def __str__(self):
        return (
            f"{self.name} ({self.start_time:%H:%M}-"
            f"{self.end_time:%H:%M}) - {self.school}"
        )

    def clean(self):
        errors = {}

        if self.name:
            self.name = self.name.strip()

        if self.order is not None and self.order < 1:
            errors["order"] = "Order must be a positive integer."

        if (
            self.start_time
            and self.end_time
            and self.start_time >= self.end_time
        ):
            errors["end_time"] = "End time must be after start time."

        if (
            self.is_active
            and self.school_id
            and self.start_time
            and self.end_time
            and self.start_time < self.end_time
        ):
            overlapping_period = (
                Period.objects.filter(
                    school_id=self.school_id,
                    is_active=True,
                    start_time__lt=self.end_time,
                    end_time__gt=self.start_time,
                )
                .exclude(pk=self.pk)
                .first()
            )

            if overlapping_period:
                errors["start_time"] = (
                    f"This period overlaps with "
                    f"'{overlapping_period.name}' "
                    f"({overlapping_period.start_time}-"
                    f"{overlapping_period.end_time})."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TimetableEntry(models.Model):
    """One scheduled classroom lesson."""

    class Weekday(models.TextChoices):
        MONDAY = "monday", "Monday"
        TUESDAY = "tuesday", "Tuesday"
        WEDNESDAY = "wednesday", "Wednesday"
        THURSDAY = "thursday", "Thursday"
        FRIDAY = "friday", "Friday"
        SATURDAY = "saturday", "Saturday"
        SUNDAY = "sunday", "Sunday"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="timetable_entries",
    )
    classroom_subject = models.ForeignKey(
        ClassroomSubject,
        on_delete=models.PROTECT,
        related_name="timetable_entries",
    )
    period = models.ForeignKey(
        Period,
        on_delete=models.PROTECT,
        related_name="timetable_entries",
    )
    weekday = models.CharField(
        max_length=10,
        choices=Weekday.choices,
    )
    room = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["school", "weekday", "period__order"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "classroom_subject",
                    "weekday",
                    "period",
                ],
                condition=models.Q(is_active=True),
                name="unique_active_class_subject_weekday_period",
            ),
        ]

    def __str__(self):
        return (
            f"{self.classroom_subject} - "
            f"{self.get_weekday_display()} @ {self.period.name}"
        )

    def clean(self):
        errors = {}

        if self.room:
            self.room = self.room.strip()

        if self.notes:
            self.notes = self.notes.strip()

        classroom_subject = None
        period = None

        if self.classroom_subject_id:
            classroom_subject = self.classroom_subject

        if self.period_id:
            period = self.period

        if classroom_subject and self.school_id:
            if classroom_subject.school_id != self.school_id:
                errors["classroom_subject"] = (
                    "The classroom subject must belong to the same school "
                    "as the timetable entry."
                )

        if period and self.school_id:
            if period.school_id != self.school_id:
                errors["period"] = (
                    "The period must belong to the same school as the "
                    "timetable entry."
                )

        if classroom_subject and not classroom_subject.is_active:
            errors["classroom_subject"] = (
                "The classroom subject must be active."
            )

        if period:
            if not period.is_active:
                errors["period"] = "The period must be active."
            elif period.is_break:
                errors["period"] = (
                    "Break periods cannot be used for lessons."
                )

        teacher = (
            classroom_subject.teacher
            if classroom_subject
            else None
        )

        if teacher:
            if not teacher.is_active:
                errors["classroom_subject"] = (
                    "The assigned teacher must be active."
                )
            elif (
                teacher.approval_status
                != User.ApprovalStatus.APPROVED
            ):
                errors["classroom_subject"] = (
                    "The assigned teacher must be approved."
                )
            elif (
                self.school_id
                and teacher.school_id != self.school_id
            ):
                errors["classroom_subject"] = (
                    "The assigned teacher must belong to the same school."
                )

        basic_fields_valid = (
            self.is_active
            and self.school_id
            and classroom_subject
            and period
            and self.weekday
        )

        if basic_fields_valid:
            conflict_qs = TimetableEntry.objects.filter(
                school_id=self.school_id,
                weekday=self.weekday,
                period_id=self.period_id,
                is_active=True,
            ).exclude(pk=self.pk)

            classroom_conflict = conflict_qs.filter(
                classroom_subject__classroom_id=(
                    classroom_subject.classroom_id
                ),
            ).exists()

            if classroom_conflict:
                errors["period"] = (
                    "This classroom already has a lesson scheduled "
                    "during this weekday and period."
                )

            if teacher:
                teacher_conflict = conflict_qs.filter(
                    classroom_subject__teacher_id=teacher.id,
                ).exists()

                if teacher_conflict:
                    errors["classroom_subject"] = (
                        "This teacher already has a lesson scheduled "
                        "during this weekday and period."
                    )

            if self.room:
                room_conflict = conflict_qs.filter(
                    room__iexact=self.room,
                ).exists()

                if room_conflict:
                    errors["room"] = (
                        "This room is already booked during this "
                        "weekday and period."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)