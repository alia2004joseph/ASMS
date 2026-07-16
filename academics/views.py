# academics/views.py

from rest_framework import permissions, viewsets
from rest_framework.exceptions import PermissionDenied

from accounts.models import User
from accounts.permissions import (
    IsApprovedUser,
    IsSchoolAdmin,
    IsStudent,
    IsTeacher,
)

from .models import (
    AcademicTerm,
    AcademicYear,
    Classroom,
    ClassroomSubject,
    StudentEnrollment,
    Subject,
)
from .serializers import (
    AcademicTermSerializer,
    AcademicYearSerializer,
    ClassroomSerializer,
    ClassroomSubjectSerializer,
    StudentEnrollmentSerializer,
    SubjectSerializer,
)


class SchoolAdminModelViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet for school-owned academic structure.

    Superusers may manage records from all schools.
    School administrators may manage records only from their own school.
    """

    permission_classes = [
        IsApprovedUser,
        IsSchoolAdmin,
    ]

    def scope_queryset_to_school(self, queryset):
        user = self.request.user

        if user.is_superuser:
            return queryset

        return queryset.filter(school=user.school)

    def perform_create(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save()
        else:
            serializer.save(school=user.school)


class AcademicYearViewSet(SchoolAdminModelViewSet):
    serializer_class = AcademicYearSerializer

    def get_queryset(self):
        queryset = AcademicYear.objects.select_related(
            "school",
        ).order_by("-start_date")

        return self.scope_queryset_to_school(queryset)


class AcademicTermViewSet(SchoolAdminModelViewSet):
    serializer_class = AcademicTermSerializer

    def get_queryset(self):
        queryset = AcademicTerm.objects.select_related(
            "school",
            "academic_year",
        ).order_by(
            "academic_year",
            "start_date",
        )

        return self.scope_queryset_to_school(queryset)


class ClassroomViewSet(SchoolAdminModelViewSet):
    serializer_class = ClassroomSerializer

    def get_queryset(self):
        queryset = Classroom.objects.select_related(
            "school",
            "academic_year",
        ).order_by(
            "school",
            "name",
        )

        return self.scope_queryset_to_school(queryset)


class SubjectViewSet(SchoolAdminModelViewSet):
    serializer_class = SubjectSerializer

    def get_queryset(self):
        queryset = Subject.objects.select_related(
            "school",
        ).order_by(
            "school",
            "name",
        )

        return self.scope_queryset_to_school(queryset)


class ClassroomSubjectViewSet(viewsets.ModelViewSet):
    """
    Administrators manage classroom-subject assignments.

    Teachers receive read-only access to assignments belonging to them.
    """

    serializer_class = ClassroomSubjectSerializer

    def get_permissions(self):
        user = self.request.user

        if (
            user.is_authenticated
            and user.role == User.Role.TEACHER
            and self.request.method in permissions.SAFE_METHODS
        ):
            return [
                IsApprovedUser(),
                IsTeacher(),
            ]

        return [
            IsApprovedUser(),
            IsSchoolAdmin(),
        ]

    def get_queryset(self):
        user = self.request.user

        queryset = ClassroomSubject.objects.select_related(
            "school",
            "classroom",
            "classroom__academic_year",
            "subject",
            "academic_term",
            "teacher",
        ).order_by(
            "classroom",
            "subject",
        )

        if not user.is_authenticated:
            return ClassroomSubject.objects.none()

        if user.is_superuser:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                teacher=user,
                school=user.school,
            )

        if user.role == User.Role.ADMIN:
            return queryset.filter(
                school=user.school,
            )

        return ClassroomSubject.objects.none()

    def perform_create(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save()
            return

        classroom = serializer.validated_data["classroom"]

        if classroom.school_id != user.school_id:
            raise PermissionDenied(
                "You may only create classroom subjects "
                "for your own school."
            )

        serializer.save(
            school=user.school,
        )

    def perform_update(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save()
            return

        classroom = serializer.validated_data.get(
            "classroom",
            serializer.instance.classroom,
        )

        if classroom.school_id != user.school_id:
            raise PermissionDenied(
                "You may only update classroom subjects "
                "from your own school."
            )

        serializer.save(
            school=user.school,
        )


class StudentEnrollmentViewSet(viewsets.ModelViewSet):
    """
    Administrators manage student enrollments.

    Students receive read-only access to their own enrollments.
    """

    serializer_class = StudentEnrollmentSerializer

    def get_permissions(self):
        user = self.request.user

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

        queryset = StudentEnrollment.objects.select_related(
            "student",
            "student__user",
            "student__school",
            "student__classroom",
            "classroom_subject",
            "classroom_subject__school",
            "classroom_subject__classroom",
            "classroom_subject__subject",
            "classroom_subject__academic_term",
        ).order_by(
            "classroom_subject",
            "student",
        )

        if not user.is_authenticated:
            return StudentEnrollment.objects.none()

        if user.is_superuser:
            return queryset

        if user.role == User.Role.STUDENT:
            try:
                student_profile = user.student_profile
            except User.student_profile.RelatedObjectDoesNotExist:
                return StudentEnrollment.objects.none()

            return queryset.filter(
                student=student_profile,
            )

        if user.role == User.Role.ADMIN:
            return queryset.filter(
                student__school=user.school,
                classroom_subject__school=user.school,
            )

        return StudentEnrollment.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        student = serializer.validated_data["student"]
        classroom_subject = serializer.validated_data[
            "classroom_subject"
        ]

        if not user.is_superuser:
            if (
                student.school_id != user.school_id
                or classroom_subject.school_id != user.school_id
            ):
                raise PermissionDenied(
                    "You may only create enrollments for "
                    "your own school."
                )

        serializer.save()

    def perform_update(self, serializer):
        user = self.request.user

        student = serializer.validated_data.get(
            "student",
            serializer.instance.student,
        )

        classroom_subject = serializer.validated_data.get(
            "classroom_subject",
            serializer.instance.classroom_subject,
        )

        if not user.is_superuser:
            if (
                student.school_id != user.school_id
                or classroom_subject.school_id != user.school_id
            ):
                raise PermissionDenied(
                    "You may only update enrollments from "
                    "your own school."
                )

        serializer.save()