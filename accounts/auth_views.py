# accounts/views_auth.py

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .auth_serializers import (
    AuthUserSerializer,
    FrontendSignupSerializer,
    LoginSerializer,
)


class LoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer =  LoginSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        return Response(
            {
                "access": serializer.validated_data[
                    "access"
                ],
                "refresh": serializer.validated_data[
                    "refresh"
                ],
                "user": AuthUserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class CurrentUserAPIView(APIView):
    permission_classes = [
        permissions.IsAuthenticated,
    ]

    def get(self, request):
        return Response(
            AuthUserSerializer(request.user).data,
            status=status.HTTP_200_OK,
        )


class SignupAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = FrontendSignupSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        return Response(
            {
                "detail": (
                    "Account created successfully and is "
                    "awaiting administrator approval."
                ),
                "user": AuthUserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PasswordResetAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = str(
            request.data.get("email", "")
        ).strip().lower()

        if email:
            user = User.objects.filter(
                email__iexact=email,
                is_active=True,
            ).first()

            if user is not None:
                # Replace this with your actual reset-token
                # email implementation later.
                try:
                    send_mail(
                        subject=(
                            "ALIA password reset request"
                        ),
                        message=(
                            "A password reset was requested "
                            "for your ALIA account."
                        ),
                        from_email=getattr(
                            settings,
                            "DEFAULT_FROM_EMAIL",
                            None,
                        ),
                        recipient_list=[user.email],
                        fail_silently=True,
                    )
                except Exception:
                    # The endpoint must still return the same response
                    # so that account existence is not leaked.
                    pass

        return Response(
            {
                "detail": (
                    "If an account exists for this email, "
                    "password reset instructions will be sent."
                )
            },
            status=status.HTTP_200_OK,
        )


class LogoutAPIView(APIView):
    permission_classes = [
        permissions.IsAuthenticated,
    ]

    def post(self, request):
        refresh_value = request.data.get("refresh")

        if not refresh_value:
            return Response(
                {
                    "detail": (
                        "The refresh token is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh_token = RefreshToken(refresh_value)
            refresh_token.blacklist()

        except TokenError:
            return Response(
                {
                    "detail": (
                        "The refresh token is invalid or expired."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "detail": "Logged out successfully."
            },
            status=status.HTTP_200_OK,
        )