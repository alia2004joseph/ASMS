# accounts/serializers.py

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .api_role_mapping import get_frontend_role
from .models import AccessCode, User


class AuthUserSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(
        source="first_name",
        read_only=True,
    )
    lastName = serializers.CharField(
        source="last_name",
        read_only=True,
    )
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "firstName",
            "lastName",
            "email",
            "role",
        ]
        read_only_fields = fields

    def get_role(self, obj):
        return get_frontend_role(obj)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    default_error_messages = {
        "invalid_credentials": (
            "No active account was found with the provided credentials."
        ),
        "not_approved": (
            "Your account is awaiting approval."
        ),
    }

    def validate(self, attrs):
        request = self.context.get("request")

        email = attrs["email"].strip().lower()
        password = attrs["password"]

        user = authenticate(
            request=request,
            email=email,
            password=password,
        )

        if user is None:
            self.fail("invalid_credentials")

        if not user.is_active:
            approval_status = getattr(
                user,
                "approval_status",
                None,
            )

            if approval_status == "pending":
                self.fail("not_approved")

            self.fail("invalid_credentials")

        approval_status = getattr(
            user,
            "approval_status",
            None,
        )

        if (
            not user.is_superuser
            and approval_status is not None
            and approval_status != "approved"
        ):
            self.fail("not_approved")

        refresh = RefreshToken.for_user(user)

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": user,
        }


class FrontendSignupSerializer(serializers.Serializer):
    accessCode = serializers.CharField(
        write_only=True,
        max_length=255,
    )
    firstName = serializers.CharField(
        write_only=True,
        max_length=150,
    )
    lastName = serializers.CharField(
        write_only=True,
        max_length=150,
    )
    email = serializers.EmailField(write_only=True)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_email(self, value):
        normalized_email = value.strip().lower()

        if User.objects.filter(
            email__iexact=normalized_email,
        ).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )

        return normalized_email

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                list(exc.messages)
            )

        return value

    def validate_accessCode(self, value):
        code_value = value.strip()

        try:
            access_code = AccessCode.objects.select_related(
                "school"
            ).get(code__iexact=code_value)
        except AccessCode.DoesNotExist:
            raise serializers.ValidationError(
                "The access code is invalid or expired."
            )

        self.context["access_code_object"] = access_code
        return code_value

    @transaction.atomic
    def create(self, validated_data):
        access_code = self.context[
            "access_code_object"
        ]

        try:
            # This assumes your existing consume() method performs
            # expiration, usage and active-state validation.
            access_code.consume()
        except DjangoValidationError:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "The access code is invalid or expired."
                    )
                }
            )

        except ValueError:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "The access code is invalid or expired."
                    )
                }
            )

        user = User.objects.create_user(
            email=validated_data["email"],
            first_name=validated_data["firstName"].strip(),
            last_name=validated_data["lastName"].strip(),
            password=validated_data["password"],
            school=access_code.school,
            role=access_code.role,
        )

        # Preserve your existing approval workflow.
        if hasattr(user, "approval_status"):
            user.approval_status = "pending"
            user.is_active = False
            user.save(
                update_fields=[
                    "approval_status",
                    "is_active",
                ]
            )

        return user