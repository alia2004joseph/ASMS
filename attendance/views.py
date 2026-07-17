# attendance/views.py

from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import (
    IsApprovedUser,
    IsSchoolAdmin,
    IsStudent,
    IsTeacher,
)

from .models import AttendanceRecord
from .serializers import AttendanceRecordSerializer


class AttendanceRecordViewSet(viewsets.ModelViewSet):
    """
    School administrators have full CRUD access within their school.

    Teachers may read, create and update attendance for lessons
    assigned to them. Teachers cannot delete attendance records.

    Students have read-only access to their own active attendance.
    """

    serializer_class = AttendanceRecordSerializer

    def get_permissions(self):
        user = self.request.user

        if user.is_authenticated and user.is_superuser:
            return [permissions.IsAuthenticated()]

        if (
            user.is_authenticated
            and user.role == User.Role.STUDENT
            and self.request.method in permissions.SAFE_METHODS
        ):
            return [
                IsApprovedUser(),
                IsStudent(),
            ]

        if (
            user.is_authenticated
            and user.role == User.Role.TEACHER
            and self.request.method
            in (
                "GET",
                "HEAD",
                "OPTIONS",
                "POST",
                "PUT",
                "PATCH",
            )
        ):
            return [
                IsApprovedUser(),
                IsTeacher(),
            ]

        return [
            IsApprovedUser(),
            IsSchoolAdmin(),
        ]

    def _base_queryset(self):
        return (
            AttendanceRecord.objects.select_related(
                "school",
                "student",
                "student__user",
                "timetable_entry",
                "timetable_entry__period",
                "timetable_entry__classroom_subject",
                "timetable_entry__classroom_subject__classroom",
                "timetable_entry__classroom_subject__subject",
                "timetable_entry__classroom_subject__teacher",
                "timetable_entry__classroom_subject__academic_term",
                "marked_by",
            )
            .order_by(
                "-date",
                "timetable_entry__period__order",
                "student_id",
            )
        )

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return AttendanceRecord.objects.none()

        queryset = self._base_queryset()

        if user.is_superuser:
            return self._apply_filters(queryset)

        if not getattr(user, "school_id", None):
            return AttendanceRecord.objects.none()

        if user.role == User.Role.TEACHER:
            queryset = queryset.filter(
                school_id=user.school_id,
                timetable_entry__classroom_subject__teacher=user,
            )

        elif user.role == User.Role.STUDENT:
            try:
                student_profile = user.student_profile
            except ObjectDoesNotExist:
                return AttendanceRecord.objects.none()

            queryset = queryset.filter(
                school_id=user.school_id,
                student=student_profile,
                is_active=True,
            )

        elif user.role == User.Role.ADMIN:
            queryset = queryset.filter(
                school_id=user.school_id,
            )

        else:
            return AttendanceRecord.objects.none()

        return self._apply_filters(queryset)

    @staticmethod
    def _validate_date(value, field_name):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise ValidationError(
                {
                    field_name: (
                        "Enter a valid date using the YYYY-MM-DD format."
                    )
                }
            )

    @staticmethod
    def _validate_integer_id(value, field_name):
        try:
            converted_value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(
                {
                    field_name: (
                        "Enter a valid numeric ID."
                    )
                }
            )

        if converted_value <= 0:
            raise ValidationError(
                {
                    field_name: (
                        "The ID must be a positive integer."
                    )
                }
            )

        return converted_value

    def _apply_filters(self, queryset):
        params = self.request.query_params

        date = params.get("date")
        if date:
            queryset = queryset.filter(
                date=self._validate_date(date, "date")
            )

        date_from = params.get("date_from")
        if date_from:
            queryset = queryset.filter(
                date__gte=self._validate_date(
                    date_from,
                    "date_from",
                )
            )

        date_to = params.get("date_to")
        if date_to:
            queryset = queryset.filter(
                date__lte=self._validate_date(
                    date_to,
                    "date_to",
                )
            )

        if date_from and date_to:
            parsed_from = self._validate_date(
                date_from,
                "date_from",
            )
            parsed_to = self._validate_date(
                date_to,
                "date_to",
            )

            if parsed_from > parsed_to:
                raise ValidationError(
                    {
                        "date_to": (
                            "date_to cannot be earlier than date_from."
                        )
                    }
                )

        classroom = params.get("classroom")
        if classroom:
            queryset = queryset.filter(
                timetable_entry__classroom_subject__classroom_id=(
                    self._validate_integer_id(
                        classroom,
                        "classroom",
                    )
                )
            )

        student = params.get("student")
        if student:
            queryset = queryset.filter(
                student_id=self._validate_integer_id(
                    student,
                    "student",
                )
            )

        status_param = params.get("status")
        if status_param:
            valid_statuses = {
                value
                for value, _label
                in AttendanceRecord.Status.choices
            }

            if status_param not in valid_statuses:
                raise ValidationError(
                    {
                        "status": (
                            "Enter a valid attendance status."
                        )
                    }
                )

            queryset = queryset.filter(status=status_param)

        timetable_entry = params.get("timetable_entry")
        if timetable_entry:
            queryset = queryset.filter(
                timetable_entry_id=self._validate_integer_id(
                    timetable_entry,
                    "timetable_entry",
                )
            )

        is_active = params.get("is_active")
        if is_active is not None:
            normalized_value = is_active.lower()

            if normalized_value not in {"true", "false"}:
                raise ValidationError(
                    {
                        "is_active": (
                            "Enter either true or false."
                        )
                    }
                )

            queryset = queryset.filter(
                is_active=normalized_value == "true"
            )

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        timetable_entry = serializer.validated_data[
            "timetable_entry"
        ]

        if not user.is_superuser:
            if not user.school_id:
                raise PermissionDenied(
                    "Your account is not assigned to a school."
                )

            if timetable_entry.school_id != user.school_id:
                raise PermissionDenied(
                    "You may only create attendance records "
                    "for your own school."
                )

            if (
                user.role == User.Role.TEACHER
                and timetable_entry.classroom_subject.teacher_id
                != user.id
            ):
                raise PermissionDenied(
                    "You may only mark attendance for your own lessons."
                )

        serializer.save(
            school=timetable_entry.school,
            marked_by=user,
        )

    def perform_update(self, serializer):
        user = self.request.user
        instance = serializer.instance

        timetable_entry = serializer.validated_data.get(
            "timetable_entry",
            instance.timetable_entry,
        )

        if not user.is_superuser:
            if not user.school_id:
                raise PermissionDenied(
                    "Your account is not assigned to a school."
                )

            if instance.school_id != user.school_id:
                raise PermissionDenied(
                    "You may only update attendance records "
                    "from your own school."
                )

            if timetable_entry.school_id != user.school_id:
                raise PermissionDenied(
                    "The selected timetable entry must belong "
                    "to your school."
                )

            if (
                user.role == User.Role.TEACHER
                and timetable_entry.classroom_subject.teacher_id
                != user.id
            ):
                raise PermissionDenied(
                    "You may only update attendance for your "
                    "own lessons."
                )

        serializer.save(
            school=timetable_entry.school,
            marked_by=user,
        )

    def perform_destroy(self, instance):
        user = self.request.user

        if (
            not user.is_superuser
            and user.role != User.Role.ADMIN
        ):
            raise PermissionDenied(
                "Only school administrators may delete "
                "attendance records."
            )

        if (
            not user.is_superuser
            and instance.school_id != user.school_id
        ):
            raise PermissionDenied(
                "You may only delete attendance records "
                "from your own school."
            )

        instance.delete()

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-mark",
    )
    def bulk_mark(self, request):
        """
        Mark attendance for multiple students atomically.

        Expected payload:

        {
            "timetable_entry": 1,
            "date": "2026-07-17",
            "records": [
                {
                    "student": 1,
                    "status": "present",
                    "remarks": ""
                }
            ]
        }
        """

        timetable_entry_id = request.data.get(
            "timetable_entry"
        )
        attendance_date = request.data.get("date")
        records = request.data.get("records")

        errors = {}

        if not timetable_entry_id:
            errors["timetable_entry"] = (
                "This field is required."
            )

        if not attendance_date:
            errors["date"] = "This field is required."

        if not isinstance(records, list):
            errors["records"] = (
                "This field must be a list."
            )
        elif not records:
            errors["records"] = (
                "At least one attendance record is required."
            )

        if errors:
            raise ValidationError(errors)

        serializers = []
        record_errors = []

        for index, entry in enumerate(records):
            if not isinstance(entry, dict):
                record_errors.append(
                    {
                        "index": index,
                        "errors": {
                            "detail": (
                                "Each record must be an object."
                            )
                        },
                    }
                )
                continue

            payload = {
                "timetable_entry": timetable_entry_id,
                "date": attendance_date,
                "student": entry.get("student"),
                "status": entry.get("status"),
                "remarks": entry.get("remarks", ""),
                "is_active": entry.get("is_active", True),
            }

            serializer = self.get_serializer(data=payload)

            if not serializer.is_valid():
                record_errors.append(
                    {
                        "index": index,
                        "student": entry.get("student"),
                        "errors": serializer.errors,
                    }
                )
            else:
                serializers.append(serializer)

        if record_errors:
            raise ValidationError(
                {"records": record_errors}
            )

        created_records = []

        # The serializer's create() method is already atomic and
        # handles model-validation and database-integrity errors.
        for serializer in serializers:
            timetable_entry = serializer.validated_data[
                "timetable_entry"
            ]

            record = serializer.save(
                school=timetable_entry.school,
                marked_by=request.user,
            )
            created_records.append(record)

        response_serializer = self.get_serializer(
            created_records,
            many=True,
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="my-attendance",
    )
    def my_attendance(self, request):
        user = request.user

        if user.role != User.Role.STUDENT:
            raise PermissionDenied(
                "Only students have a personal attendance record."
            )

        try:
            student_profile = user.student_profile
        except ObjectDoesNotExist:
            return Response([])

        queryset = self._base_queryset().filter(
            school_id=user.school_id,
            student=student_profile,
            is_active=True,
        )

        queryset = self._apply_filters(queryset)

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(
            queryset,
            many=True,
        )
        return Response(serializer.data)