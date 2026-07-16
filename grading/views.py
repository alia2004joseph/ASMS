# grading/views.py

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import (
    IsApprovedUser,
    IsSchoolAdmin,
    IsStudent,
    IsTeacher,
)

from .models import (
    Assessment,
    AssessmentType,
    Grade,
    GradeHistory,
    GradeStatus,
    SubjectApprovalStatus,
    SubjectGradeApproval,
)
from .serializers import (
    AssessmentSerializer,
    AssessmentTypeSerializer,
    GradeHistorySerializer,
    GradeSerializer,
    SubjectGradeApprovalSerializer,
)


def is_admin(user):
    return bool(
        user.is_superuser
        or user.role == User.Role.ADMIN
    )


def is_teacher(user):
    return user.role == User.Role.TEACHER


def is_student(user):
    return user.role == User.Role.STUDENT


class AssessmentTypeViewSet(viewsets.ModelViewSet):
    serializer_class = AssessmentTypeSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [IsApprovedUser()]

        return [
            IsApprovedUser(),
            IsSchoolAdmin(),
        ]

    def get_queryset(self):
        user = self.request.user

        queryset = AssessmentType.objects.select_related(
            "school",
        ).order_by("name")

        if not user.is_authenticated:
            return AssessmentType.objects.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return AssessmentType.objects.none()

        return queryset.filter(
            school=user.school,
        )

    def perform_create(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save()
        else:
            serializer.save(
                school=user.school,
            )


class AssessmentViewSet(viewsets.ModelViewSet):
    serializer_class = AssessmentSerializer

    def get_permissions(self):
        user = self.request.user

        if self.request.method in permissions.SAFE_METHODS:
            return [IsApprovedUser()]

        if (
            user.is_authenticated
            and user.role == User.Role.TEACHER
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

        queryset = Assessment.objects.select_related(
            "school",
            "classroom_subject",
            "classroom_subject__classroom",
            "classroom_subject__subject",
            "classroom_subject__academic_term",
            "classroom_subject__teacher",
            "assessment_type",
        ).order_by(
            "assessment_date",
            "title",
        )

        if not user.is_authenticated:
            return Assessment.objects.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return Assessment.objects.none()

        queryset = queryset.filter(
            school=user.school,
        )

        if is_admin(user):
            return queryset

        if is_teacher(user):
            return queryset.filter(
                classroom_subject__teacher=user,
            )

        if is_student(user):
            return queryset.filter(
                classroom_subject__student_enrollments__student__user=user,
            ).distinct()

        return Assessment.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        classroom_subject = serializer.validated_data[
            "classroom_subject"
        ]

        if user.is_superuser:
            serializer.save()
            return

        if not is_teacher(user):
            raise PermissionDenied(
                "Only teachers may create assessments."
            )

        if classroom_subject.teacher_id != user.id:
            raise PermissionDenied(
                "You may only create assessments for subjects "
                "assigned to you."
            )

        serializer.save(
            school=user.school,
        )

    def perform_update(self, serializer):
        user = self.request.user

        classroom_subject = serializer.validated_data.get(
            "classroom_subject",
            serializer.instance.classroom_subject,
        )

        if user.is_superuser:
            serializer.save()
            return

        if not is_teacher(user):
            raise PermissionDenied(
                "Only teachers may update assessments."
            )

        if classroom_subject.teacher_id != user.id:
            raise PermissionDenied(
                "You may only update assessments for subjects "
                "assigned to you."
            )

        serializer.save(
            school=user.school,
        )


class GradeViewSet(viewsets.ModelViewSet):
    serializer_class = GradeSerializer

    def get_permissions(self):
        user = self.request.user

        if self.request.method in permissions.SAFE_METHODS:
            return [IsApprovedUser()]

        if (
            user.is_authenticated
            and user.role == User.Role.TEACHER
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

        queryset = Grade.objects.select_related(
            "school",
            "student_enrollment",
            "student_enrollment__student",
            "student_enrollment__student__user",
            "student_enrollment__classroom_subject",
            "assessment",
            "assessment__assessment_type",
            "assessment__classroom_subject",
            "recorded_by",
        ).order_by("-created_at")

        if not user.is_authenticated:
            return Grade.objects.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return Grade.objects.none()

        queryset = queryset.filter(
            school=user.school,
        )

        if is_admin(user):
            return queryset

        if is_teacher(user):
            return queryset.filter(
                student_enrollment__classroom_subject__teacher=user,
                recorded_by=user,
            )

        if is_student(user):
            return queryset.filter(
                student_enrollment__student__user=user,
                status=GradeStatus.APPROVED,
            )

        return Grade.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        enrollment = serializer.validated_data[
            "student_enrollment"
        ]

        if not is_teacher(user):
            raise PermissionDenied(
                "Only teachers may record grades."
            )

        if (
            enrollment.classroom_subject.teacher_id
            != user.id
        ):
            raise PermissionDenied(
                "You may only record grades for your assigned "
                "classroom subjects."
            )

        serializer.save(
            school=user.school,
            recorded_by=user,
        )

    def perform_update(self, serializer):
        user = self.request.user
        grade = serializer.instance

        if not is_teacher(user):
            raise PermissionDenied(
                "Only teachers may edit grades."
            )

        if grade.recorded_by_id != user.id:
            raise PermissionDenied(
                "You may only edit grades recorded by you."
            )

        if grade.status == GradeStatus.APPROVED:
            raise PermissionDenied(
                "Approved grades cannot be edited."
            )

        serializer.save()

    def perform_destroy(self, instance):
        if instance.status != GradeStatus.DRAFT:
            raise PermissionDenied(
                "Only draft grades may be deleted."
            )

        instance.delete()

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        grade = self.get_object()

        if not is_teacher(request.user):
            return Response(
                {"detail": "Only teachers may submit grades."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if grade.recorded_by_id != request.user.id:
            return Response(
                {"detail": "You may only submit grades recorded by you."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if grade.status != GradeStatus.DRAFT:
            return Response(
                {"detail": "Only draft grades may be submitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status = grade.status
        grade.status = GradeStatus.SUBMITTED
        grade.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        GradeHistory.objects.create(
            grade=grade,
            changed_by=request.user,
            old_score=grade.score,
            new_score=grade.score,
            old_status=old_status,
            new_status=GradeStatus.SUBMITTED,
            reason="Submitted by teacher.",
        )

        return Response(
            self.get_serializer(grade).data,
            status=status.HTTP_200_OK,
        )


class GradeHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GradeHistorySerializer

    permission_classes = [
        IsApprovedUser,
    ]

    def get_queryset(self):
        user = self.request.user

        queryset = GradeHistory.objects.select_related(
            "grade",
            "grade__school",
            "grade__student_enrollment",
            "grade__student_enrollment__classroom_subject",
            "changed_by",
        ).order_by("-changed_at")

        if not user.is_authenticated:
            return GradeHistory.objects.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return GradeHistory.objects.none()

        queryset = queryset.filter(
            grade__school=user.school,
        )

        if is_admin(user):
            return queryset

        if is_teacher(user):
            return queryset.filter(
                grade__student_enrollment__classroom_subject__teacher=user,
            )

        return GradeHistory.objects.none()


class SubjectGradeApprovalViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectGradeApprovalSerializer

    def get_permissions(self):
        user = self.request.user

        if self.action == "create":
            if (
                user.is_authenticated
                and user.role == User.Role.TEACHER
            ):
                return [
                    IsApprovedUser(),
                    IsTeacher(),
                ]

            return [
                IsApprovedUser(),
                IsSchoolAdmin(),
            ]

        if self.action in {
            "approve",
            "reject",
            "update",
            "partial_update",
            "destroy",
        }:
            return [
                IsApprovedUser(),
                IsSchoolAdmin(),
            ]

        return [IsApprovedUser()]

    def get_queryset(self):
        user = self.request.user

        queryset = SubjectGradeApproval.objects.select_related(
            "school",
            "classroom_subject",
            "classroom_subject__teacher",
            "approved_by",
        ).order_by("-created_at")

        if not user.is_authenticated:
            return SubjectGradeApproval.objects.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return SubjectGradeApproval.objects.none()

        queryset = queryset.filter(
            school=user.school,
        )

        if is_admin(user):
            return queryset

        if is_teacher(user):
            return queryset.filter(
                classroom_subject__teacher=user,
            )

        return SubjectGradeApproval.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        classroom_subject = serializer.validated_data[
            "classroom_subject"
        ]

        if user.is_superuser:
            serializer.save()
            return

        if not is_teacher(user):
            raise PermissionDenied(
                "Only teachers may submit subject grades."
            )

        if classroom_subject.teacher_id != user.id:
            raise PermissionDenied(
                "You may only submit grades for subjects "
                "assigned to you."
            )

        serializer.save(
            school=user.school,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        approval = self.get_object()

        approval.apply_decision(
            SubjectApprovalStatus.APPROVED,
            request.user,
            request.data.get("remarks", ""),
        )

        approval.refresh_from_db()

        return Response(
            self.get_serializer(approval).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        approval = self.get_object()

        approval.apply_decision(
            SubjectApprovalStatus.REJECTED,
            request.user,
            request.data.get("remarks", ""),
        )

        approval.refresh_from_db()

        return Response(
            self.get_serializer(approval).data,
            status=status.HTTP_200_OK,
        )