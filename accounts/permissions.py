# accounts/permissions.py

from rest_framework.permissions import BasePermission

from .models import User


class IsApprovedUser(BasePermission):
    """Allows only authenticated, active and approved users."""

    message = "Your account must be approved before using this feature."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and (
                user.is_superuser
                or user.approval_status
                == User.ApprovalStatus.APPROVED
            )
        )





class IsSchoolAdmin(BasePermission):
    """
    Allows access only to approved and active school administrators.

    Superusers always pass.

    Non-superusers must:
    - be authenticated;
    - be active;
    - have an approved account;
    - have the ADMIN role;
    - belong to a school.

    Querysets and serializers must still enforce school-level data isolation.
    """

    message = (
        "Only approved school administrators can perform this action."
    )

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return (
            user.is_active
            and user.approval_status == User.ApprovalStatus.APPROVED
            and user.role == User.Role.ADMIN
            and user.school_id is not None
        )


class IsTeacher(BasePermission):
    """Allows only approved teachers."""

    message = "Only approved teachers can perform this action."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.approval_status
            == User.ApprovalStatus.APPROVED
            and user.role == User.Role.TEACHER
            and user.school_id is not None
        )


class IsStudent(BasePermission):
    """Allows only approved students."""

    message = "Only approved students can perform this action."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.approval_status
            == User.ApprovalStatus.APPROVED
            and user.role == User.Role.STUDENT
            and user.school_id is not None
        )


class IsGuardian(BasePermission):
    """Allows only approved guardians."""

    message = "Only approved guardians can perform this action."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.approval_status
            == User.ApprovalStatus.APPROVED
            and user.role == User.Role.GUARDIAN
            and user.school_id is not None
        )


class IsAccountant(BasePermission):
    """Allows only approved accountants."""

    message = "Only approved accountants can perform this action."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.approval_status
            == User.ApprovalStatus.APPROVED
            and user.role == User.Role.ACCOUNTANT
            and user.school_id is not None
        )