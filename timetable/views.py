# timetable/views.py

from django.core.exceptions import (
    ObjectDoesNotExist,
    ValidationError as DjangoValidationError,
)
from django.db.models import Case, IntegerField, Value, When
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import (
    IsApprovedUser,
    IsSchoolAdmin,
    IsStudent,
    IsTeacher,
)

from .models import Period, TimetableEntry
from .serializers import (
    PeriodSerializer,
    TimetableEntrySerializer,
)


class PeriodViewSet(viewsets.ModelViewSet):
    """
    School admins manage periods in their own school.

    Teachers and students have read-only access to active periods
    belonging to their school.
    """

    serializer_class = PeriodSerializer

    def get_permissions(self):
        user = self.request.user

        if user.is_authenticated and user.is_superuser:
            return [permissions.IsAuthenticated()]

        if (
            user.is_authenticated
            and user.role == User.Role.TEACHER
            and self.request.method in permissions.SAFE_METHODS
        ):
            return [
                IsApprovedUser(),
                IsTeacher(),
            ]

        if (
            user.is_authenticated
            and user.role == User.Role.STUDENT
            and self.request.method in permissions.SAFE_METHODS
        ):
            return [
                IsApprovedUser(),
                IsStudent(),
            ]

        return [
            IsApprovedUser(),
            IsSchoolAdmin(),
        ]

    def get_queryset(self):
        user = self.request.user

        queryset = Period.objects.select_related(
            "school",
        ).order_by(
            "school_id",
            "order",
        )

        if not user.is_authenticated:
            return Period.objects.none()

        if user.is_superuser:
            return queryset

        if not getattr(user, "school_id", None):
            return Period.objects.none()

        queryset = queryset.filter(
            school_id=user.school_id,
        )

        if user.role in (
            User.Role.TEACHER,
            User.Role.STUDENT,
        ):
            queryset = queryset.filter(is_active=True)

        elif user.role != User.Role.ADMIN:
            return Period.objects.none()

        return queryset

    def perform_create(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save()
            return

        if not user.school_id:
            raise PermissionDenied(
                "Your account is not assigned to a school."
            )

        serializer.save(school=user.school)

    def perform_update(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save()
            return

        if not user.school_id:
            raise PermissionDenied(
                "Your account is not assigned to a school."
            )

        if serializer.instance.school_id != user.school_id:
            raise PermissionDenied(
                "You may only update periods from your own school."
            )

        serializer.save(school=user.school)


class TimetableEntryViewSet(viewsets.ModelViewSet):
    """
    School admins manage timetable entries in their own school.

    Teachers see entries assigned to them.
    Students see entries belonging to their classroom.
    """

    serializer_class = TimetableEntrySerializer

    def get_permissions(self):
        user = self.request.user

        if user.is_authenticated and user.is_superuser:
            return [permissions.IsAuthenticated()]

        if self.action == "my_schedule":
            if (
                user.is_authenticated
                and user.role == User.Role.TEACHER
            ):
                return [
                    IsApprovedUser(),
                    IsTeacher(),
                ]

            if (
                user.is_authenticated
                and user.role == User.Role.STUDENT
            ):
                return [
                    IsApprovedUser(),
                    IsStudent(),
                ]

            return [permissions.IsAuthenticated()]

        if (
            user.is_authenticated
            and user.role == User.Role.TEACHER
            and self.request.method in permissions.SAFE_METHODS
        ):
            return [
                IsApprovedUser(),
                IsTeacher(),
            ]

        if (
            user.is_authenticated
            and user.role == User.Role.STUDENT
            and self.request.method in permissions.SAFE_METHODS
        ):
            return [
                IsApprovedUser(),
                IsStudent(),
            ]

        return [
            IsApprovedUser(),
            IsSchoolAdmin(),
        ]

    def _base_queryset(self):
        weekday_order = Case(
            When(
                weekday=TimetableEntry.Weekday.MONDAY,
                then=Value(1),
            ),
            When(
                weekday=TimetableEntry.Weekday.TUESDAY,
                then=Value(2),
            ),
            When(
                weekday=TimetableEntry.Weekday.WEDNESDAY,
                then=Value(3),
            ),
            When(
                weekday=TimetableEntry.Weekday.THURSDAY,
                then=Value(4),
            ),
            When(
                weekday=TimetableEntry.Weekday.FRIDAY,
                then=Value(5),
            ),
            When(
                weekday=TimetableEntry.Weekday.SATURDAY,
                then=Value(6),
            ),
            When(
                weekday=TimetableEntry.Weekday.SUNDAY,
                then=Value(7),
            ),
            output_field=IntegerField(),
        )

        return (
            TimetableEntry.objects.select_related(
                "school",
                "period",
                "classroom_subject",
                "classroom_subject__classroom",
                "classroom_subject__subject",
                "classroom_subject__teacher",
                "classroom_subject__academic_term",
            )
            .annotate(weekday_order=weekday_order)
            .order_by(
                "school_id",
                "weekday_order",
                "period__order",
            )
        )

    def _active_schedule_queryset(self):
        return self._base_queryset().filter(
            is_active=True,
            period__is_active=True,
            classroom_subject__is_active=True,
        )

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return TimetableEntry.objects.none()

        if user.is_superuser:
            queryset = self._base_queryset()

        elif not getattr(user, "school_id", None):
            return TimetableEntry.objects.none()

        elif user.role == User.Role.TEACHER:
            queryset = self._active_schedule_queryset().filter(
                school_id=user.school_id,
                classroom_subject__teacher=user,
            )

        elif user.role == User.Role.STUDENT:
            classroom_id = self._get_student_classroom_id(user)

            if classroom_id is None:
                return TimetableEntry.objects.none()

            queryset = self._active_schedule_queryset().filter(
                school_id=user.school_id,
                classroom_subject__classroom_id=classroom_id,
            )

        elif user.role == User.Role.ADMIN:
            queryset = self._base_queryset().filter(
                school_id=user.school_id,
            )

        else:
            return TimetableEntry.objects.none()

        return self._apply_filters(queryset)

    @staticmethod
    def _get_student_classroom_id(user):
        try:
            student_profile = user.student_profile
        except ObjectDoesNotExist:
            return None

        return getattr(student_profile, "classroom_id", None)

    def _convert_filter_id(self, query_value, model_field, name):
        try:
            return model_field.to_python(query_value)
        except (
            DjangoValidationError,
            TypeError,
            ValueError,
        ):
            raise DRFValidationError(
                {name: f"'{query_value}' is not a valid ID."}
            )

    def _apply_filters(self, queryset):
        params = self.request.query_params
        user = self.request.user

        weekday = params.get("weekday")

        if weekday:
            valid_weekdays = {
                value
                for value, _label
                in TimetableEntry.Weekday.choices
            }

            if weekday not in valid_weekdays:
                raise DRFValidationError(
                    {
                        "weekday": (
                            "Enter a valid weekday such as monday, "
                            "tuesday, or wednesday."
                        )
                    }
                )

            queryset = queryset.filter(weekday=weekday)

        classroom = params.get("classroom")

        if classroom:
            classroom_field = (
                TimetableEntry._meta.get_field(
                    "classroom_subject"
                )
                .related_model._meta.get_field("classroom")
                .target_field
            )

            classroom_id = self._convert_filter_id(
                classroom,
                classroom_field,
                "classroom",
            )

            queryset = queryset.filter(
                classroom_subject__classroom_id=classroom_id,
            )

        teacher = params.get("teacher")

        if teacher:
            teacher_field = (
                TimetableEntry._meta.get_field(
                    "classroom_subject"
                )
                .related_model._meta.get_field("teacher")
                .target_field
            )

            teacher_id = self._convert_filter_id(
                teacher,
                teacher_field,
                "teacher",
            )

            queryset = queryset.filter(
                classroom_subject__teacher_id=teacher_id,
            )

        academic_term = params.get("academic_term")

        if academic_term:
            term_field = (
                TimetableEntry._meta.get_field(
                    "classroom_subject"
                )
                .related_model._meta.get_field("academic_term")
                .target_field
            )

            academic_term_id = self._convert_filter_id(
                academic_term,
                term_field,
                "academic_term",
            )

            queryset = queryset.filter(
                classroom_subject__academic_term_id=(
                    academic_term_id
                ),
            )

        # Filters can only narrow an already role-scoped queryset.
        # These explicit restrictions provide defence in depth.
        if user.role == User.Role.TEACHER:
            queryset = queryset.filter(
                classroom_subject__teacher=user,
            )

        elif user.role == User.Role.STUDENT:
            classroom_id = self._get_student_classroom_id(user)

            if classroom_id is None:
                return TimetableEntry.objects.none()

            queryset = queryset.filter(
                classroom_subject__classroom_id=classroom_id,
            )

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        classroom_subject = serializer.validated_data[
            "classroom_subject"
        ]

        if user.is_superuser:
            serializer.save(
                school=classroom_subject.school,
            )
            return

        if not user.school_id:
            raise PermissionDenied(
                "Your account is not assigned to a school."
            )

        if classroom_subject.school_id != user.school_id:
            raise PermissionDenied(
                "You may only create timetable entries for "
                "your own school."
            )

        serializer.save(school=user.school)

    def perform_update(self, serializer):
        user = self.request.user

        classroom_subject = serializer.validated_data.get(
            "classroom_subject",
            serializer.instance.classroom_subject,
        )

        if user.is_superuser:
            serializer.save(
                school=classroom_subject.school,
            )
            return

        if not user.school_id:
            raise PermissionDenied(
                "Your account is not assigned to a school."
            )

        if serializer.instance.school_id != user.school_id:
            raise PermissionDenied(
                "You may only update timetable entries "
                "from your own school."
            )

        if classroom_subject.school_id != user.school_id:
            raise PermissionDenied(
                "The selected classroom subject must belong "
                "to your own school."
            )

        serializer.save(school=user.school)

    @action(
        detail=False,
        methods=["get"],
        url_path="my-schedule",
    )
    def my_schedule(self, request):
        user = request.user

        if user.is_superuser or user.role == User.Role.ADMIN:
            raise PermissionDenied(
                "Administrators should use the standard list "
                "endpoint to view timetable entries."
            )

        if user.role == User.Role.TEACHER:
            queryset = self._active_schedule_queryset().filter(
                school_id=user.school_id,
                classroom_subject__teacher=user,
            )

        elif user.role == User.Role.STUDENT:
            classroom_id = self._get_student_classroom_id(user)

            if classroom_id is None:
                return Response([])

            queryset = self._active_schedule_queryset().filter(
                school_id=user.school_id,
                classroom_subject__classroom_id=classroom_id,
            )

        else:
            raise PermissionDenied(
                "Your role does not have access to a "
                "personal schedule."
            )

        queryset = self._apply_filters(queryset)

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)