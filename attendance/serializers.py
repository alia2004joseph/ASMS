# attendance/serializers.py

from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db import IntegrityError, transaction
from rest_framework import serializers

from accounts.models import User
from academics.models import StudentEnrollment

from .models import AttendanceRecord


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()

    classroom_name = serializers.CharField(
        source=(
            "timetable_entry.classroom_subject.classroom.name"
        ),
        read_only=True,
    )
    subject_name = serializers.CharField(
        source="timetable_entry.classroom_subject.subject.name",
        read_only=True,
    )
    teacher_name = serializers.SerializerMethodField()

    weekday = serializers.CharField(
        source="timetable_entry.weekday",
        read_only=True,
    )
    marked_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceRecord
        fields = [
            "id",
            "school",
            "timetable_entry",
            "student",
            "date",
            "status",
            "marked_by",
            "remarks",
            "is_active",
            "student_name",
            "classroom_name",
            "subject_name",
            "teacher_name",
            "weekday",
            "marked_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "marked_by",
            "created_at",
            "updated_at",
        ]

    def get_student_name(self, obj):
        user = obj.student.user
        full_name = user.get_full_name()
        return full_name or str(user)

    def get_teacher_name(self, obj):
        teacher = (
            obj.timetable_entry.classroom_subject.teacher
        )

        if teacher is None:
            return None

        full_name = teacher.get_full_name()
        return full_name or str(teacher)

    def get_marked_by_name(self, obj):
        if obj.marked_by is None:
            return None

        full_name = obj.marked_by.get_full_name()
        return full_name or str(obj.marked_by)

    def get_request_user(self):
        request = self.context.get("request")

        if request is None:
            return None

        return request.user

    def validate(self, attrs):
        user = self.get_request_user()

        timetable_entry = attrs.get(
            "timetable_entry",
            getattr(self.instance, "timetable_entry", None),
        )
        student = attrs.get(
            "student",
            getattr(self.instance, "student", None),
        )
        date = attrs.get(
            "date",
            getattr(self.instance, "date", None),
        )
        is_active = attrs.get(
            "is_active",
            getattr(self.instance, "is_active", True),
        )

        remarks = attrs.get(
            "remarks",
            getattr(self.instance, "remarks", ""),
        )

        errors = {}

        if timetable_entry is None:
            errors["timetable_entry"] = (
                "This field is required."
            )

        if student is None:
            errors["student"] = "This field is required."

        if date is None:
            errors["date"] = "This field is required."

        if errors:
            raise serializers.ValidationError(errors)

        school = timetable_entry.school
        classroom_subject = timetable_entry.classroom_subject
        period = timetable_entry.period

        if user is None or not user.is_authenticated:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "An authenticated user is required to "
                        "manage attendance."
                    )
                }
            )

        if not user.is_superuser:
            if not user.school_id:
                errors["school"] = (
                    "Your account is not assigned to a school."
                )

            elif user.school_id != school.id:
                errors["timetable_entry"] = (
                    "You may only manage attendance for your "
                    "own school."
                )

            if user.role == User.Role.TEACHER:
                if classroom_subject.teacher_id != user.id:
                    errors["timetable_entry"] = (
                        "You may only mark attendance for your "
                        "own lessons."
                    )

            elif user.role != User.Role.ADMIN:
                errors["detail"] = (
                    "Only teachers and school administrators "
                    "may manage attendance."
                )

        if student.school_id != school.id:
            errors["student"] = (
                "The student must belong to the same school "
                "as the timetable entry."
            )

        if not timetable_entry.is_active:
            errors["timetable_entry"] = (
                "Attendance cannot be recorded for an inactive "
                "timetable entry."
            )

        elif not period.is_active:
            errors["timetable_entry"] = (
                "Attendance cannot be recorded during an "
                "inactive period."
            )

        elif period.is_break:
            errors["timetable_entry"] = (
                "Attendance cannot be recorded during a break "
                "period."
            )

        elif not classroom_subject.is_active:
            errors["timetable_entry"] = (
                "Attendance cannot be recorded for an inactive "
                "classroom subject."
            )

        if not student.is_active_student:
            errors["student"] = (
                "Attendance cannot be recorded for an inactive "
                "student."
            )

        elif not student.user.is_active:
            errors["student"] = (
                "The student's account must be active."
            )

        elif (
            student.user.approval_status
            != User.ApprovalStatus.APPROVED
        ):
            errors["student"] = (
                "The student's account must be approved."
            )

        enrollment_queryset = StudentEnrollment.objects.filter(
            student=student,
            classroom_subject=classroom_subject,
            is_active=True,
        )

        if not enrollment_queryset.exists():
            errors["student"] = (
                "The student is not actively enrolled in this "
                "classroom subject."
            )

        if is_active and date:
            duplicate_queryset = AttendanceRecord.objects.filter(
                student=student,
                timetable_entry=timetable_entry,
                date=date,
                is_active=True,
            )

            if self.instance is not None:
                duplicate_queryset = duplicate_queryset.exclude(
                    pk=self.instance.pk
                )

            if duplicate_queryset.exists():
                errors["date"] = (
                    "An active attendance record already exists "
                    "for this student, timetable entry and date."
                )

        if errors:
            raise serializers.ValidationError(errors)

        attrs["school"] = school
        attrs["marked_by"] = user
        attrs["remarks"] = remarks.strip() if remarks else ""

        return attrs

    @staticmethod
    def _convert_model_validation_error(exc):
        if hasattr(exc, "message_dict"):
            return serializers.ValidationError(
                exc.message_dict
            )

        return serializers.ValidationError(
            {"detail": exc.messages}
        )

    @transaction.atomic
    def create(self, validated_data):
        try:
            return AttendanceRecord.objects.create(
                **validated_data
            )

        except DjangoValidationError as exc:
            raise self._convert_model_validation_error(exc)

        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "An active attendance record already "
                        "exists for this student, timetable "
                        "entry and date."
                    )
                }
            )

    @transaction.atomic
    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)

        try:
            instance.save()
            return instance

        except DjangoValidationError as exc:
            raise self._convert_model_validation_error(exc)

        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "An active attendance record already "
                        "exists for this student, timetable "
                        "entry and date."
                    )
                }
            )