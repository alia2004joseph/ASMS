"""
Production serializers for fee-clearance certificate issuance,
regeneration, revocation, and verification.

All balance decisions remain authoritative in the Finance service layer.
The serializer validates request shape only and delegates lifecycle
operations to reports.services.certificate_service.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from reports.constants import VerificationResult
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.fee_clearance import FeeClearanceCertificate
from reports.services import certificate_service


MAX_REASON_LENGTH = 2_000


def _request(serializer: serializers.BaseSerializer):
    request = serializer.context.get("request")
    if request is None:
        raise serializers.ValidationError(
            "Serializer request context is required."
        )
    return request


def _school(serializer: serializers.BaseSerializer):
    request = _request(serializer)
    school = getattr(request.user, "school", None)

    if school is None and not getattr(
        request.user,
        "is_superuser",
        False,
    ):
        raise serializers.ValidationError(
            "The authenticated user is not assigned to a school."
        )

    return school


def _as_serializer_error(exc: Exception) -> serializers.ValidationError:
    if hasattr(exc, "message_dict"):
        return serializers.ValidationError(exc.message_dict)
    if hasattr(exc, "messages"):
        return serializers.ValidationError(exc.messages)
    return serializers.ValidationError(str(exc))


class FeeClearanceIssueRequestSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)
    academic_year_id = serializers.IntegerField(min_value=1)
    term_id = serializers.IntegerField(min_value=1)

    admin_override = serializers.BooleanField(default=False)

    override_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        max_length=MAX_REASON_LENGTH,
    )

    override_threshold = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
        min_value=Decimal("0.00"),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = _request(self)
        school = _school(self)

        admin_override = attrs.get("admin_override", False)
        override_reason = attrs.get("override_reason", "").strip()
        override_threshold = attrs.get(
            "override_threshold",
            Decimal("0.00"),
        )

        if admin_override and not override_reason:
            raise serializers.ValidationError(
                {
                    "override_reason": (
                        "override_reason is required when "
                        "admin_override is true."
                    )
                }
            )

        if not admin_override:
            attrs["override_reason"] = ""
            attrs["override_threshold"] = Decimal("0.00")

        try:
            certificate_service.validate_fee_clearance_issue_request(
                school=school,
                student_id=attrs["student_id"],
                academic_year_id=attrs["academic_year_id"],
                term_id=attrs["term_id"],
                admin_override=admin_override,
                override_reason=attrs["override_reason"],
                override_threshold=override_threshold,
                issued_by=request.user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

        return attrs

    def create(
        self,
        validated_data: dict[str, Any],
    ) -> FeeClearanceCertificate:
        request = _request(self)
        school = _school(self)

        try:
            return certificate_service.issue_fee_clearance_certificate(
                school=school,
                student_id=validated_data["student_id"],
                academic_year_id=validated_data["academic_year_id"],
                term_id=validated_data["term_id"],
                admin_override=validated_data.get(
                    "admin_override",
                    False,
                ),
                override_reason=validated_data.get(
                    "override_reason",
                    "",
                ),
                override_threshold=validated_data.get(
                    "override_threshold",
                    Decimal("0.00"),
                ),
                issued_by=request.user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

    def update(self, instance, validated_data):
        raise NotImplementedError(
            "Fee-clearance issuance requests cannot be updated."
        )


class FeeClearanceCertificateSerializer(
    serializers.ModelSerializer
):
    student_id = serializers.IntegerField(
        source="student_id",
        read_only=True,
    )
    academic_year_id = serializers.IntegerField(
        source="academic_year_id",
        read_only=True,
    )
    term_id = serializers.IntegerField(
        source="term_id",
        read_only=True,
    )
    previous_version_id = serializers.IntegerField(
        source="previous_version_id",
        read_only=True,
        allow_null=True,
    )
    issued_by_id = serializers.IntegerField(
        source="issued_by_id",
        read_only=True,
        allow_null=True,
    )
    revoked_by_id = serializers.IntegerField(
        source="revoked_by_id",
        read_only=True,
        allow_null=True,
    )
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = FeeClearanceCertificate
        fields = (
            "id",
            "student_id",
            "academic_year_id",
            "term_id",
            "cleared_amount",
            "outstanding_balance",
            "clearance_status",
            "certificate_number",
            "verification_code",
            "version",
            "root_id",
            "previous_version_id",
            "is_latest",
            "is_revoked",
            "revoked_reason",
            "revoked_at",
            "revoked_by_id",
            "regeneration_reason",
            "issued_at",
            "issued_by_id",
            "file_url",
            "status",
        )
        read_only_fields = fields

    def get_file_url(
        self,
        obj: FeeClearanceCertificate,
    ) -> str | None:
        file_field = getattr(obj, "file", None)

        if not file_field:
            return None

        try:
            url = file_field.url
        except (ValueError, AttributeError):
            return None

        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(url)

        return url


class FeeClearanceRegenerateRequestSerializer(
    serializers.Serializer
):
    reason = serializers.CharField(
        trim_whitespace=True,
        min_length=3,
        max_length=MAX_REASON_LENGTH,
    )

    def validate_reason(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "A regeneration reason is required."
            )
        return value

    def save(self, **kwargs) -> FeeClearanceCertificate:
        previous = kwargs.get(
            "previous",
            self.context.get("certificate"),
        )

        if previous is None:
            raise serializers.ValidationError(
                "Fee-clearance certificate context is required."
            )

        request = _request(self)

        try:
            return certificate_service.regenerate_fee_clearance_certificate(
                previous=previous,
                reason=self.validated_data["reason"],
                generated_by=request.user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc


class FeeClearanceRevokeRequestSerializer(
    serializers.Serializer
):
    reason = serializers.CharField(
        trim_whitespace=True,
        min_length=3,
        max_length=MAX_REASON_LENGTH,
    )

    def validate_reason(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "A revocation reason is required."
            )
        return value

    def save(self, **kwargs) -> FeeClearanceCertificate:
        certificate = kwargs.get(
            "certificate",
            self.context.get("certificate"),
        )

        if certificate is None:
            raise serializers.ValidationError(
                "Fee-clearance certificate context is required."
            )

        request = _request(self)

        try:
            return certificate_service.revoke_fee_clearance_certificate(
                certificate=certificate,
                reason=self.validated_data["reason"],
                revoked_by=request.user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc


class FeeClearanceVerifyResponseSerializer(
    serializers.Serializer
):
    result = serializers.ChoiceField(
        choices=VerificationResult.choices,
    )
    certificate_number = serializers.CharField(
        required=False,
        allow_blank=False,
    )
    clearance_status = serializers.CharField(
        required=False,
        allow_blank=False,
    )
    issued_at = serializers.DateTimeField(required=False)
    version = serializers.IntegerField(
        required=False,
        min_value=1,
    )
    is_official = serializers.BooleanField(required=False)