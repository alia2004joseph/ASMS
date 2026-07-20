"""
Production serializers for ID card issuance, regeneration, revocation,
and verification.

Business logic is delegated to reports.services.certificate_service.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from reports.constants import VerificationResult
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.id_cards import IDCard
from reports.services import certificate_service
from reports.constants import IDCardHolderType

MAX_REASON = 2000


def _request(serializer):
    request = serializer.context.get("request")
    if request is None:
        raise serializers.ValidationError("Request context is required.")
    return request


def _school(serializer):
    request = _request(serializer)
    school = getattr(request.user, "school", None)
    if school is None and not getattr(request.user, "is_superuser", False):
        raise serializers.ValidationError("Authenticated user has no school.")
    return school


def _error(exc):
    if hasattr(exc, "message_dict"):
        return serializers.ValidationError(exc.message_dict)
    if hasattr(exc, "messages"):
        return serializers.ValidationError(exc.messages)
    return serializers.ValidationError(str(exc))


class IDCardIssueRequestSerializer(serializers.Serializer):
    holder_type = serializers.ChoiceField(
    choices=IDCardHolderType.choices
)
    holder_id = serializers.IntegerField(min_value=1)
    identification_number = serializers.CharField(max_length=255)
    role_label = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    role_context = serializers.JSONField(required=False, default=dict)
    valid_from = serializers.DateField()
    valid_until = serializers.DateField()
    emergency_contact = serializers.JSONField(required=False, allow_null=True, default=None)

    def validate_role_context(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("role_context must be a JSON object.")
        return value

    def validate_emergency_contact(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("emergency_contact must be a JSON object.")
        return value

    def validate(self, attrs):
        if attrs["valid_until"] <= attrs["valid_from"]:
            raise serializers.ValidationError(
                {"valid_until": "valid_until must be after valid_from."}
            )

        request = _request(self)

        try:
            certificate_service.validate_id_card_issue_request(
                school=_school(self),
                issued_by=request.user,
                **attrs,
            )
        except (DomainValidationError, DjangoValidationError) as exc:
            raise _error(exc) from exc

        return attrs

    def create(self, validated_data):
        request = _request(self)
        try:
            return certificate_service.issue_id_card(
                school=_school(self),
                issued_by=request.user,
                **validated_data,
            )
        except (DomainValidationError, DjangoValidationError) as exc:
            raise _error(exc) from exc


class IDCardSerializer(serializers.ModelSerializer):
    holder_id = serializers.IntegerField(source="holder_id", read_only=True)
    issued_by_id = serializers.IntegerField(source="issued_by_id", read_only=True, allow_null=True)
    previous_version_id = serializers.IntegerField(source="previous_version_id", read_only=True, allow_null=True)
    revoked_by_id = serializers.IntegerField(source="revoked_by_id", read_only=True, allow_null=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = IDCard
        fields = (
            "id",
            "holder_type",
            "holder_id",
            "identification_number",
            "role_label",
            "role_context",
            "valid_from",
            "valid_until",
            "verification_code",
            "card_status",
            "version",
            "root_id",
            "previous_version_id",
            "is_latest",
            "is_revoked",
            "revoked_reason",
            "revoked_at",
            "revoked_by_id",
            "issued_by_id",
            "status",
            "file_url",
        )
        read_only_fields = fields

    def get_file_url(self, obj):
        if not getattr(obj, "file", None):
            return None
        try:
            url = obj.file.url
        except Exception:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class IDCardRegenerateRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=MAX_REASON, trim_whitespace=True)

    def save(self, **kwargs):
        previous = kwargs.get("previous", self.context.get("card"))
        if previous is None:
            raise serializers.ValidationError("ID card context is required.")
        request = _request(self)
        try:
            return certificate_service.regenerate_id_card(
                previous=previous,
                reason=self.validated_data["reason"],
                generated_by=request.user,
            )
        except (DomainValidationError, DjangoValidationError) as exc:
            raise _error(exc) from exc


class IDCardRevokeRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=MAX_REASON, trim_whitespace=True)

    def save(self, **kwargs):
        card = kwargs.get("card", self.context.get("card"))
        if card is None:
            raise serializers.ValidationError("ID card context is required.")
        request = _request(self)
        try:
            return certificate_service.revoke_id_card(
                card=card,
                reason=self.validated_data["reason"],
                revoked_by=request.user,
            )
        except (DomainValidationError, DjangoValidationError) as exc:
            raise _error(exc) from exc


class IDCardVerifyResponseSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=VerificationResult.choices)
    holder_type = serializers.CharField(required=False)
    identification_number = serializers.CharField(required=False)
    valid_until = serializers.DateField(required=False)
    version = serializers.IntegerField(required=False, min_value=1)
    card_status = serializers.CharField(required=False)