# accounts/serializers.py
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import AccessCode, GuardianStudentLink, User


class UserSerializer(serializers.ModelSerializer):
    """General-purpose read representation of a user."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "school",
            "approval_status",
            "is_active",
            "profile_picture",
            "date_joined",
        ]
        read_only_fields = fields


class ProfileSerializer(serializers.ModelSerializer):
    """
    Lets an authenticated user view/edit their own limited profile
    fields. role, school, and approval fields are read-only here —
    they're only ever changed via AccountApprovalSerializer / the
    User.approve()/reject() methods, never by the user themselves.
    Classroom and student_id_number live on StudentProfile, not User,
    so they're naturally excluded from this serializer already.
    """

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "profile_picture",
            "role",
            "school",
            "approval_status",
        ]
        read_only_fields = [
            "id",
            "email",
            "role",
            "school",
            "approval_status",
        ]


class PendingUserSerializer(serializers.ModelSerializer):
    """Representation used in the pending-accounts admin list/approval flow."""

    school_name = serializers.CharField(source="school.name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "school",
            "school_name",
            "approval_status",
            "rejection_reason",
            "date_joined",
        ]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    """
    Public registration using a valid access code. The code determines
    school and role, so those are never accepted directly from the
    client.

    validate_access_code() only checks the code is currently valid; it
    does NOT consume it. The actual AccessCode.consume() call happens
    in create(), so that a code is never burned unless the whole
    registration (password strength, uniqueness, etc.) also succeeds.
    RegisterView.create() additionally wraps the whole request in
    @transaction.atomic, so this is defense in depth rather than the
    only thing preventing a wasted code use.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(
    max_length=150, required=False, allow_blank=True
    )
    access_code = serializers.CharField(write_only=True)

    def validate_password(self, value):
        try:
            password_validation.validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate_email(self, value):
        email = value.strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )

        return email

    def validate_access_code(self, value):
        normalized_code = value.strip().upper()

        try:
            access_code = AccessCode.objects.get(code=normalized_code)
        except AccessCode.DoesNotExist:
            raise serializers.ValidationError("The access code is invalid.")

        if not access_code.is_valid():
            raise serializers.ValidationError(
                "The access code is inactive, expired, or fully used."
            )

        return normalized_code

    @transaction.atomic
    def create(self, validated_data):
        access_code_value = validated_data.pop("access_code")
        password = validated_data.pop("password")

        try:
            access_code = AccessCode.consume(access_code_value)

            user = User.objects.create_user(
                email=validated_data["email"],
                password=password,
                first_name=validated_data["first_name"],
                last_name=validated_data.get("last_name", ""),
                role=access_code.role,
                school=access_code.school,
                is_active=False,
                approval_status=User.ApprovalStatus.PENDING,
            )

        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {
                    "detail": getattr(
                        exc,
                        "messages",
                        [str(exc)],
                    )
                }
            )
        return user
    

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    JWT login. Django's authenticate() already refuses is_active=False
    users (which covers PENDING and REJECTED accounts, since neither
    ever gets is_active=True), so the base class blocks them.

    We additionally distinguish *why* login failed — but only after
    confirming the password was actually correct. Revealing "your
    account is pending" (or even that the account exists) to someone
    who hasn't proven they know the password would let an attacker
    enumerate registered emails and their approval status by guessing.
    """

    def validate(self, attrs):
        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            self._raise_status_specific_error(attrs)
            raise

        data["user"] = UserSerializer(self.user).data
        return data

    def _raise_status_specific_error(self, attrs):
        email = attrs.get(self.username_field)
        password = attrs.get("password")

        try:
            candidate = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return

        if not candidate.check_password(password):
            return

        if candidate.approval_status == User.ApprovalStatus.PENDING:
            raise serializers.ValidationError(
                {"detail": "Your account is awaiting administrator approval."}
            )

        if candidate.approval_status == User.ApprovalStatus.REJECTED:
            raise serializers.ValidationError(
                {"detail": "Your account registration was rejected."}
            )


class AccountApprovalSerializer(serializers.Serializer):
    """
    Backs both AccountApprovalView (single) and BulkAccountApprovalView
    (context={"bulk": True}).

    Enforces that 'reason' is present and non-blank whenever
    action=reject, BEFORE the view ever calls User.reject(). This is
    what actually prevents User.reject()'s own ValidationError (raised
    when reason is blank) from bubbling up as an unhandled 500 in
    views.py — the view trusts this serializer to have already
    guaranteed a valid reason.
    """

    class Action(models.TextChoices):
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"

    action = serializers.ChoiceField(choices=Action.choices)
    reason = serializers.CharField(required=False, allow_blank=True)
    user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
    )

    def validate(self, attrs):
        if self.context.get("bulk") and not attrs.get("user_ids"):
            raise serializers.ValidationError(
                {"user_ids": "This field is required for bulk actions."}
            )

        if attrs["action"] == self.Action.REJECT:
            reason = attrs.get("reason", "").strip()
            if not reason:
                raise serializers.ValidationError(
                    {
                        "reason": (
                            "A rejection reason is required when rejecting "
                            "an account."
                        )
                    }
                )
            attrs["reason"] = reason

        return attrs


class AccessCodeSerializer(serializers.ModelSerializer):
    """
    'school' is writable for superusers (AccessCodeViewSet.perform_create
    relies on this — it lets a superuser pick which school a new code
    belongs to) but forced read-only for non-superuser admins. Without
    this, a school admin could PATCH an existing code's 'school' to a
    different school after creation, since AccessCodeViewSet has no
    perform_update() override to catch that.
    """

    class Meta:
        model = AccessCode
        fields = [
            "id",
            "code",
            "school",
            "role",
            "max_uses",
            "times_used",
            "expires_at",
            "is_active",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["code", "times_used", "created_by", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        user = getattr(request, "user", None)

        if user and not user.is_superuser:
            self.fields["school"].read_only = True

    def validate_role(self, value):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if user and user.is_superuser:
            return value

        allowed_roles = {
            User.Role.STUDENT,
            User.Role.GUARDIAN,
            User.Role.TEACHER,
        }

        if value not in allowed_roles:
            raise serializers.ValidationError(
                "Access codes may only be created for "
                "students, guardians, or teachers."
            )

        return value

    def validate(self, attrs):
        instance = self.instance

        max_uses = attrs.get(
            "max_uses",
            getattr(instance, "max_uses", None),
        )

        times_used = getattr(instance, "times_used", 0)

        if max_uses is not None and max_uses < times_used:
            raise serializers.ValidationError(
                {
                    "max_uses": (
                        "Maximum uses cannot be less than "
                        "the number already used."
                    )
                }
            )

        return attrs



class GuardianStudentLinkSerializer(serializers.ModelSerializer):
    """
    Validates that, for a non-superuser admin, both the guardian and
    the student belong to that admin's own school. Without this, a
    school admin could link a guardian/student pair belonging entirely
    to a different school — GuardianStudentLink.clean() on the model
    only checks that guardian and student share a school with each
    other, not that either belongs to the requesting admin's school.
    """

    class Meta:
        model = GuardianStudentLink
        fields = [
            "id",
            "guardian",
            "student",
            "relationship",
            "is_primary_guardian",
            "can_receive_notifications",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        guardian = attrs.get(
            "guardian", getattr(self.instance, "guardian", None)
        )
        student = attrs.get(
            "student", getattr(self.instance, "student", None)
        )

        if user and not user.is_superuser and user.role == User.Role.ADMIN:
            if guardian and guardian.school_id != user.school_id:
                raise serializers.ValidationError(
                    {"guardian": "Guardian must belong to your own school."}
                )
            if student and student.school_id != user.school_id:
                raise serializers.ValidationError(
                    {"student": "Student must belong to your own school."}
                )

        return attrs