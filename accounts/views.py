# accounts/views.py

from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import generics, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from rest_framework_simplejwt.views import TokenObtainPairView

from .models import AccessCode, GuardianStudentLink, User
from .permissions import IsSchoolAdmin
from .serializers import (
    AccessCodeSerializer,
    AccountApprovalSerializer,
    CustomTokenObtainPairSerializer,
    GuardianStudentLinkSerializer,
    PendingUserSerializer,
    ProfileSerializer,
    RegisterSerializer,
    UserSerializer,
)


class RegisterView(generics.CreateAPIView):
    """
    Register a student, teacher or guardian using a valid access code.

    The RegisterSerializer is responsible for:
    - validating the access code;
    - assigning the school;
    - assigning the role;
    - creating the user securely;
    - consuming the access code;
    - setting approval_status to pending.
    """

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "registration"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        return Response(
            {
                "message": (
                    "Registration submitted successfully. "
                    "Your account is awaiting administrator approval."
                ),
                "user": UserSerializer(
                    user,
                    context=self.get_serializer_context(),
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomLoginView(TokenObtainPairView):
    """
    JWT login endpoint.

    CustomTokenObtainPairSerializer should prevent pending, rejected,
    or inactive accounts from receiving tokens.
    """

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class CurrentUserView(generics.RetrieveAPIView):
    """Return the currently authenticated user's account information."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class ProfileView(generics.RetrieveUpdateAPIView):
    """
    Allow an authenticated user to view and edit permitted profile fields.

    The ProfileSerializer must exclude or mark as read-only:
    - role;
    - school;
    - classroom;
    - student ID;
    - approval status;
    - approved_by;
    - approved_at.

    Students and guardians should only update fields such as:
    - first_name;
    - last_name;
    - profile_picture.
    """

    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def perform_update(self, serializer):
        serializer.save()


class PendingAccountListView(generics.ListAPIView):
    """
    List pending accounts belonging to the administrator's school.

    Supports optional role filtering:

        /api/accounts/pending/?role=student
        /api/accounts/pending/?role=teacher
        /api/accounts/pending/?role=guardian
    """

    serializer_class = PendingUserSerializer
    permission_classes = [IsAuthenticated, IsSchoolAdmin]

    def get_queryset(self):
        queryset = (
            User.objects.filter(
                approval_status=User.ApprovalStatus.PENDING,
            )
            .select_related("school", "approved_by")
            .order_by("date_joined")
        )

        user = self.request.user

        if not user.is_superuser:
            queryset = queryset.filter(school=user.school)

        requested_role = self.request.query_params.get("role")

        if requested_role:
            queryset = queryset.filter(role=requested_role)

        return queryset


class AccountApprovalView(APIView):
    """
    Approve or reject one pending account.

    Expected request body:

        {
            "action": "approve"
        }

    or:

        {
            "action": "reject",
            "reason": "The supplied student details could not be verified."
        }
    """

    permission_classes = [IsAuthenticated, IsSchoolAdmin]

    def post(self, request, user_id):
        serializer = AccountApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_user = self._get_target_user(request.user, user_id)

        action = serializer.validated_data["action"]
        reason = serializer.validated_data.get("reason", "")

        if target_user.approval_status != User.ApprovalStatus.PENDING:
            return Response(
                {
                    "detail": (
                        "Only pending accounts may be approved or rejected."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if target_user == request.user:
            return Response(
                {"detail": "You cannot approve or reject your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == AccountApprovalSerializer.Action.APPROVE:
            target_user.approve(approved_by=request.user)
            message = "Account approved successfully."
        else:
            target_user.reject(
                approved_by=request.user,
                reason=reason,
            )
            message = "Account rejected successfully."

        return Response(
            {
                "message": message,
                "user": PendingUserSerializer(target_user).data,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_target_user(admin_user, user_id):
        queryset = User.objects.select_related("school")

        if not admin_user.is_superuser:
            queryset = queryset.filter(school=admin_user.school)

        return get_object_or_404(queryset, pk=user_id)


class BulkAccountApprovalView(APIView):
    """
    Approve or reject several pending accounts in one action.

    Expected approval request:

        {
            "user_ids": [4, 7, 9],
            "action": "approve"
        }

    Expected rejection request:

        {
            "user_ids": [4, 7, 9],
            "action": "reject",
            "reason": "Registration information was not verified."
        }
    """

    permission_classes = [IsAuthenticated, IsSchoolAdmin]

    @transaction.atomic
    def post(self, request):
        serializer = AccountApprovalSerializer(
            data=request.data,
            context={"bulk": True},
        )
        serializer.is_valid(raise_exception=True)

        user_ids = serializer.validated_data["user_ids"]
        action = serializer.validated_data["action"]
        reason = serializer.validated_data.get("reason", "")

        queryset = User.objects.select_for_update().filter(
            id__in=user_ids,
            approval_status=User.ApprovalStatus.PENDING,
        )

        if not request.user.is_superuser:
            queryset = queryset.filter(school=request.user.school)

        target_users = list(queryset.exclude(id=request.user.id))

        found_ids = {user.id for user in target_users}
        missing_ids = sorted(set(user_ids) - found_ids)

        approved_count = 0
        rejected_count = 0

        for target_user in target_users:
            if action == AccountApprovalSerializer.Action.APPROVE:
                target_user.approve(approved_by=request.user)
                approved_count += 1
            else:
                target_user.reject(
                    approved_by=request.user,
                    reason=reason,
                )
                rejected_count += 1

        return Response(
            {
                "message": "Bulk account action completed.",
                "approved_count": approved_count,
                "rejected_count": rejected_count,
                "unprocessed_user_ids": missing_ids,
            },
            status=status.HTTP_200_OK,
        )


class AccessCodeViewSet(viewsets.ModelViewSet):
    """
    Allow administrators to create and manage school access codes.

    Non-superuser administrators only see codes belonging to their school.
    """

    serializer_class = AccessCodeSerializer
    permission_classes = [IsAuthenticated, IsSchoolAdmin]

    def get_queryset(self):
        queryset = AccessCode.objects.select_related(
            "school",
            "created_by",
        ).order_by("-created_at")

        if self.request.user.is_superuser:
            return queryset

        return queryset.filter(school=self.request.user.school)

    def perform_create(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save(created_by=user)
        else:
            serializer.save(
                school=user.school,
                created_by=user,
            )


class GuardianStudentLinkViewSet(viewsets.ModelViewSet):
    """
    Manage guardian-to-student relationships.

    School administrators manage all links in their own school.
    Guardians may only view their own links.
    """

    serializer_class = GuardianStudentLinkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = GuardianStudentLink.objects.select_related(
            "guardian",
            "student",
            "guardian__school",
            "student__school",
        )

        user = self.request.user

        if user.is_superuser:
            return queryset

        if user.role == User.Role.ADMIN:
            return queryset.filter(guardian__school=user.school)

        if user.role == User.Role.GUARDIAN:
            return queryset.filter(guardian=user)

        if user.role == User.Role.STUDENT:
            return queryset.filter(student=user)

        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user

        if not (
            user.is_superuser
            or user.role == User.Role.ADMIN
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "Only administrators can create guardian-student links."
            )

        serializer.save()