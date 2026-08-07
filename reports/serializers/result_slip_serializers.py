"""
Production serializers for result-slip generation, regeneration,
revocation, and verification.

Grade computation and business rules remain authoritative in
reports.services.result_slip_service. These serializers validate request
shape only and delegate to that service.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from reports.constants import VerificationResult
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.result_slips import ResultSlip
from reports.services import result_slip_service


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
        request.user, "is_superuser", False,
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


def _resolve(app_label: str, model_name: str, pk: int, *, field_name: str):
    Model = apps.get_model(app_label, model_name)
    try:
        return Model.objects.get(pk=pk)
    except Model.DoesNotExist as exc:
        raise serializers.ValidationError(
            {field_name: f"No matching {model_name} was found."}
        ) from exc


class ResultSlipGenerateRequestSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)
    academic_year_id = serializers.IntegerField(min_value=1)
    term_id = serializers.IntegerField(min_value=1)
    class_id = serializers.IntegerField(min_value=1)
    show_position = serializers.BooleanField(default=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Existence is checked here so invalid IDs surface as normal
        # serializer validation errors instead of service-layer exceptions.
        attrs["_student"] = _resolve(
            "accounts", "StudentProfile", attrs["student_id"],
            field_name="student_id",
        )
        attrs["_academic_year"] = _resolve(
            "academics", "AcademicYear", attrs["academic_year_id"],
            field_name="academic_year_id",
        )
        attrs["_term"] = _resolve(
            "academics", "AcademicTerm", attrs["term_id"],
            field_name="term_id",
        )
        attrs["_classroom"] = _resolve(
            "academics", "Classroom", attrs["class_id"],
            field_name="class_id",
        )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> ResultSlip:
        request = _request(self)
        school = _school(self)

        try:
            return result_slip_service.generate_result_slip(
                student=validated_data["_student"],
                academic_year=validated_data["_academic_year"],
                term=validated_data["_term"],
                class_ref=validated_data["_classroom"],
                school=school,
                show_position=validated_data.get("show_position", True),
                generated_by=request.user,
            )
        except (DomainValidationError, DjangoValidationError) as exc:
            raise _as_serializer_error(exc) from exc

    def update(self, instance, validated_data):
        raise NotImplementedError(
            "Result-slip generation requests cannot be updated."
        )


class ResultSlipSerializer(serializers.ModelSerializer):
    student_id = serializers.IntegerField(read_only=True)
    academic_year_id = serializers.IntegerField(read_only=True)
    term_id = serializers.IntegerField(read_only=True)
    classroom_id = serializers.IntegerField(read_only=True)
    previous_version_id = serializers.IntegerField(
        read_only=True, allow_null=True,
    )
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ResultSlip
        fields = (
            "id",
            "student_id",
            "academic_year_id",
            "term_id",
            "classroom_id",
            "subjects_snapshot",
            "aggregate_or_gpa",
            "position",
            "class_average",
            "pass_fail_status",
            "verification_code",
            "version",
            "root_id",
            "previous_version_id",
            "is_latest",
            "is_revoked",
            "file_url",
            "status",
            "created_at",
        )
        read_only_fields = fields

    def get_file_url(self, obj: ResultSlip) -> str | None:
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


class ResultSlipRegenerateRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(
        trim_whitespace=True, min_length=3, max_length=MAX_REASON_LENGTH,
    )

    def validate_reason(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "A regeneration reason is required."
            )
        return value

    def save(self, **kwargs) -> ResultSlip:
        previous = kwargs.get("previous", self.context.get("result_slip"))
        if previous is None:
            raise serializers.ValidationError(
                "Result slip context is required."
            )

        request = _request(self)
        try:
            return result_slip_service.regenerate_result_slip(
                previous=previous,
                reason=self.validated_data["reason"],
                generated_by=request.user,
            )
        except (DomainValidationError, DjangoValidationError) as exc:
            raise _as_serializer_error(exc) from exc


class ResultSlipRevokeRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(
        trim_whitespace=True, min_length=3, max_length=MAX_REASON_LENGTH,
    )

    def validate_reason(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "A revocation reason is required."
            )
        return value

    def save(self, **kwargs) -> ResultSlip:
        slip = kwargs.get("slip", self.context.get("result_slip"))
        if slip is None:
            raise serializers.ValidationError(
                "Result slip context is required."
            )

        request = _request(self)
        try:
            return result_slip_service.revoke_result_slip(
                slip=slip,
                reason=self.validated_data["reason"],
                revoked_by=request.user,
            )
        except (DomainValidationError, DjangoValidationError) as exc:
            raise _as_serializer_error(exc) from exc


class ResultSlipVerifyResponseSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=VerificationResult.choices)
    result_slip_id = serializers.IntegerField(required=False)
    term_id = serializers.IntegerField(required=False)
    academic_year_id = serializers.IntegerField(required=False)
