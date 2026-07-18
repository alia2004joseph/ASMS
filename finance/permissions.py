# finance/permissions.py

from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import GuardianStudentLink, User


class IsFinanceManager(BasePermission):
    """
    Allows full finance access to superusers, approved school admins and
    approved accountants, scoped to their own school at the object level.
    """

    message = "Only school administrators or accountants can manage finance records."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated or not user.is_active:
            return False

        if user.is_superuser:
            return True

        return bool(
            user.approval_status == User.ApprovalStatus.APPROVED
            and user.role in (User.Role.ADMIN, User.Role.ACCOUNTANT)
            and user.school_id is not None
        )

    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_superuser:
            return True

        school_id = getattr(obj, "school_id", None)

        return school_id is not None and school_id == user.school_id


class IsOwnStudentOrLinkedGuardianReadOnly(BasePermission):
    """
    Allows read-only access to students viewing their own finance records,
    and to guardians viewing finance records of students linked to them.
    """

    message = "You may only view your own finance records."

    def has_permission(self, request, view):
        user = request.user

        if request.method not in SAFE_METHODS:
            return False

        if not user or not user.is_authenticated or not user.is_active:
            return False

        return bool(
            user.approval_status == User.ApprovalStatus.APPROVED
            and user.role in (User.Role.STUDENT, User.Role.GUARDIAN)
        )

    def has_object_permission(self, request, view, obj):
        user = request.user

        if request.method not in SAFE_METHODS:
            return False

        # Determine the student associated with the object.
        if hasattr(obj, "student"):
            student_profile = obj.student
        elif hasattr(obj, "payment"):
            student_profile = obj.payment.student
        elif hasattr(obj, "invoice"):
            student_profile = obj.invoice.student
        else:
            return False

        if user.role == User.Role.STUDENT:
            return student_profile.user_id == user.id

        if user.role == User.Role.GUARDIAN:
            if not hasattr(request, "_guardian_student_ids"):
                request._guardian_student_ids = set(
                    GuardianStudentLink.objects.filter(
                        guardian=user
                    ).values_list(
                        "student_id",
                        flat=True,
                    )
                )

            return student_profile.user_id in request._guardian_student_ids

        return False