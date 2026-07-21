"""
Certificate serializers aligned with the current certificate service.

Supported service operations:
- issue_certificate
- revoke_certificate
- verify

Certificate template administration uses the model serializer directly.
Certificate regeneration remains explicitly unavailable until a matching
service-layer operation is implemented.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from reports.constants import VerificationResult
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.certificates import Certificate, CertificateTemplate
from reports.services import certificate_service


def _request_from_context(serializer: serializers.BaseSerializer):
    request = serializer.context.get("request")
    if request is None:
        raise serializers.ValidationError(
            "Serializer request context is required."
        )
    return request


def _request_school(serializer: serializers.BaseSerializer):
    request = _request_from_context(serializer)
    user = getattr(request, "user", None)

    if user is None:
        raise serializers.ValidationError(
            "Authenticated user context is required."
        )

    school = getattr(user, "school", None)

    if school is None and not getattr(user, "is_superuser", False):
        raise serializers.ValidationError(
            "The authenticated user is not assigned to a school."
        )

    return school


def _domain_error(exc: Exception) -> serializers.ValidationError:
    if hasattr(exc, "message_dict"):
        return serializers.ValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        return serializers.ValidationError(exc.messages)

    return serializers.ValidationError(str(exc))


def _student_model():
    """
    Resolve the concrete student model from Certificate.student.

    This avoids coupling the reports app to a hard-coded student app path.
    """
    return Certificate._meta.get_field("student").remote_field.model


class CertificateIssueRequestSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(min_value=1)

    certificate_type = serializers.ChoiceField(
        choices=CertificateTemplate.CERTIFICATE_TYPES,
    )

    template_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        school = _request_school(self)

        if school is None:
            raise serializers.ValidationError(
                "A school is required to issue certificates."
            )

        student_model = _student_model()

        try:
            student = student_model.objects.get(
                pk=attrs["student_id"],
                school=school,
            )
        except student_model.DoesNotExist as exc:
            raise serializers.ValidationError(
                {
                    "student_id": (
                        "No student with this ID exists in your school."
                    )
                }
            ) from exc

        template = None
        template_id = attrs.get("template_id")

        if template_id is not None:
            try:
                template = CertificateTemplate.objects.get(
                    pk=template_id,
                    school=school,
                    certificate_type=attrs["certificate_type"],
                    is_active=True,
                )
            except CertificateTemplate.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {
                        "template_id": (
                            "No active certificate template with this ID "
                            "and certificate type exists in your school."
                        )
                    }
                ) from exc

        attrs["_student"] = student
        attrs["_template"] = template
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Certificate:
        request = _request_from_context(self)
        school = _request_school(self)

        student = validated_data.pop("_student")
        template = validated_data.pop("_template", None)

        try:
            return certificate_service.issue_certificate(
                student=student,
                school=school,
                certificate_type=validated_data["certificate_type"],
                issued_by=request.user,
                template=template,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _domain_error(exc) from exc

    def update(self, instance, validated_data):
        raise NotImplementedError(
            "Certificate issuance requests cannot be updated."
        )


class CertificateSerializer(serializers.ModelSerializer):
    student_id = serializers.IntegerField(read_only=True)

    template_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )

    previous_version_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )

    issued_by_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )

    revoked_by_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )

    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Certificate

        fields = (
            "id",
            "student_id",
            "certificate_type",
            "template_id",
            "serial_number",
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

    def get_file_url(self, obj: Certificate) -> str | None:
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


class CertificateRevokeRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(
        trim_whitespace=True,
        min_length=3,
        max_length=2_000,
    )

    def validate_reason(self, value: str) -> str:
        reason = value.strip()

        if not reason:
            raise serializers.ValidationError(
                "A revocation reason is required."
            )

        return reason

    def save(self, **kwargs) -> Certificate:
        certificate = kwargs.get(
            "certificate",
            self.context.get("certificate"),
        )

        if certificate is None:
            raise serializers.ValidationError(
                "Certificate context is required."
            )

        request = _request_from_context(self)

        try:
            return certificate_service.revoke_certificate(
                certificate=certificate,
                reason=self.validated_data["reason"],
                revoked_by=request.user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _domain_error(exc) from exc


class CertificateRegenerateRequestSerializer(serializers.Serializer):
    """
    Request contract retained for API compatibility.

    A regeneration service does not yet exist in certificate_service.py,
    therefore save() fails explicitly instead of calling a missing function.
    """

    reason = serializers.CharField(
        trim_whitespace=True,
        min_length=3,
        max_length=2_000,
    )

    template_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        certificate = self.context.get("certificate")

        if certificate is None:
            raise serializers.ValidationError(
                "Certificate context is required."
            )

        school = _request_school(self)
        template_id = attrs.get("template_id")

        if template_id is not None:
            try:
                template = CertificateTemplate.objects.get(
                    pk=template_id,
                    school=school,
                    certificate_type=certificate.certificate_type,
                    is_active=True,
                )
            except CertificateTemplate.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {
                        "template_id": (
                            "No matching active certificate template "
                            "exists in your school."
                        )
                    }
                ) from exc

            attrs["_template"] = template

        return attrs

    def save(self, **kwargs):
        raise serializers.ValidationError(
            "Certificate regeneration is not available because the "
            "certificate service has no regeneration operation."
        )


class CertificateVerifyResponseSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=VerificationResult.choices,
    )

    serial_number = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    certificate_type = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    issued_at = serializers.DateTimeField(required=False)

    is_official = serializers.BooleanField(required=False)

    version = serializers.IntegerField(
        required=False,
        min_value=1,
    )

    student_name = serializers.CharField(
        required=False,
        allow_blank=False,
    )


class CertificateTemplateSerializer(serializers.ModelSerializer):
    school_id = serializers.IntegerField(read_only=True)

    created_by_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = CertificateTemplate

        fields = (
            "id",
            "school_id",
            "certificate_type",
            "layout_config",
            "signature_fields",
            "is_active",
            "version",
            "created_by_id",
        )

        read_only_fields = (
            "id",
            "school_id",
            "version",
            "created_by_id",
        )

    def validate_layout_config(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "layout_config must be a JSON object."
            )

        return value

    def validate_signature_fields(
        self,
        value: Any,
    ) -> list[Any] | dict[str, Any]:
        if not isinstance(value, (list, dict)):
            raise serializers.ValidationError(
                "signature_fields must be a JSON array or object."
            )

        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        school = _request_school(self)

        if school is None:
            raise serializers.ValidationError(
                "A school is required to manage certificate templates."
            )

        certificate_type = attrs.get(
            "certificate_type",
            getattr(self.instance, "certificate_type", None),
        )

        queryset = CertificateTemplate.objects.filter(
            school=school,
            certificate_type=certificate_type,
        )

        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                {
                    "certificate_type": (
                        "A certificate template with this type already "
                        "exists in your school."
                    )
                }
            )

        return attrs

    def create(
        self,
        validated_data: dict[str, Any],
    ) -> CertificateTemplate:
        request = _request_from_context(self)
        school = _request_school(self)

        return CertificateTemplate.objects.create(
            school=school,
            created_by=request.user,
            **validated_data,
        )

    def update(
        self,
        instance: CertificateTemplate,
        validated_data: dict[str, Any],
    ) -> CertificateTemplate:
        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.full_clean()
        instance.save()
        return instance