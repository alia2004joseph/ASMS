# communications/permissions.py

from rest_framework.permissions import BasePermission

from accounts.models import User


def _approved_active(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (
            user.is_superuser
            or user.approval_status == User.ApprovalStatus.APPROVED
        )
    )


class IsCommunicationManager(BasePermission):
    """
    Admins, teachers and accountants may create/manage communications.

    Fine-grained rules (teacher classroom scope, accountant restriction to
    finance-type communications, admin-only emergency broadcasts and
    school-wide audiences) are enforced in the service layer and in
    has_object_permission below, since they depend on the specific
    communication's audience/type rather than the endpoint alone.
    """

    message = "You are not authorized to manage communications."

    def has_permission(self, request, view):
        user = request.user

        if not _approved_active(user):
            return False

        if user.is_superuser:
            return True

        return (
            user.role in (User.Role.ADMIN, User.Role.TEACHER, User.Role.ACCOUNTANT)
            and user.school_id is not None
        )

    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_superuser:
            return True

        if obj.school_id != user.school_id:
            return False

        if user.role == User.Role.ADMIN:
            return True

        # Non-admin managers may only act on their own drafts/submissions.
        return obj.created_by_id == user.id


class IsApprovedSchoolMember(BasePermission):
    """Any approved, active user attached to a school (used for inbox/prefs)."""

    message = "Your account must be approved before using this feature."

    def has_permission(self, request, view):
        user = request.user
        return bool(_approved_active(user) and (user.is_superuser or user.school_id))
