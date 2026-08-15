"""
Permission classes skeleton.

These are minimal DRF permission class placeholders. Real implementations must
use service-layer checks and reference ASMS models via get_model or lazy
imports to avoid circular imports at module load time.
"""

from rest_framework.permissions import BasePermission
from django.conf import settings
from django.apps import apps


class IsAdminUser(BasePermission):
    """Allow access only to admin users (role-based)."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # Conservative check: rely on User.role == 'admin' or is_superuser
        role = getattr(user, "role", None)
        return user.is_superuser or role == getattr(user, "Role", {}).get("ADMIN") or role == "ADMIN"


class IsClassRepForClassroomOrSubject(BasePermission):
    """Placeholder: Allow if user has an active ClassRepresentativeAssignment.

    Real implementation should check ClassRepresentativeAssignment model and
    ensure assignment matches target classroom or classroom_subject and term.
    """

    def has_object_permission(self, request, view, obj):
        # obj may be a classroom or classroom_subject instance
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Defer detailed checks to service layer to avoid import-time DB access.
        return False


class IsTeacherForClassroomSubject(BasePermission):
    """Allow if user is assigned teacher for the classroom subject."""

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # Real logic: check obj.teacher_id == user.id
        return False
