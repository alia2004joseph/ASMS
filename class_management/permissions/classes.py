from rest_framework.permissions import BasePermission
from .models import ClassRepresentativeAssignment

class IsClassRep(BasePermission):
    """
    Allows access if the user is an appointed, active Class Representative.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.role in ['ADMIN', 'LECTURER']:
            return True
        
        # Check if student has an active rep assignment
        return ClassRepresentativeAssignment.objects.filter(
            student__user=request.user,
            status='ACTIVE'
        ).exists()


class IsLecturerOrAdmin(BasePermission):
    """
    Allows access only to Lecturers and System Administrators.
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and 
            request.user.role in ['LECTURER', 'ADMIN']
        )


class IsEnrolledStudent(BasePermission):
    """
    Ensures student is actively enrolled in the requested classroom / subject.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated
