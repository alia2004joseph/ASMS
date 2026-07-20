"""
Production serializers for certificate issuance, revocation, verification,
and template administration.

All certificate lifecycle operations are delegated to
reports.services.certificate_service. Clients cannot set school, audit,
verification, file, versioning, or status fields directly.
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
    school = getattr(request.user, "school", None)

    if school is None and not getattr(request.user, "is_superuser", False):
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


class CertificateIssueRequestSerializer(serializers.Serializer):
    """
    Validates a certificate issuance command.

    The view may call ``save()`` to issue the certificate through the
    authoritative certificate service.
    """

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
        request = _request_from_context(self)

        template_id = attrs.get("template_id")
        if template_id is not None:
            template_queryset = CertificateTemplate.objects.filter(
                pk=template_id,
                certificate_type=attrs["certificate_type"],
                is_active=True,
            )

            if school is not None:
                template_queryset = template_queryset.filter(
                    school=school,
                )

            if not template_queryset.exists():
                raise serializers.ValidationError(
                    {
                        "template_id": (
                            "No active certificate template with this ID "
                            "and certificate type exists in your school."
                        )
                    }
                )

        try:
            certificate_service.validate_issue_request(
                school=school,
                student_id=attrs["student_id"],
                certificate_type=attrs["certificate_type"],
                template_id=template_id,
                issued_by=request.user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _domain_error(exc) from exc

        return attrs

    def create(self, validated_data: dict[str, Any]) -> Certificate:
        request = _request_from_context(self)
        school = _request_school(self)

        try:
            return certificate_service.issue_certificate(
                school=school,
                student_id=validated_data["student_id"],
                certificate_type=validated_data["certificate_type"],
                template_id=validated_data.get("template_id"),
                issued_by=request.user,
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
    student_id = serializers.IntegerField(
        source="student_id",
        read_only=True,
    )
    template_id = serializers.IntegerField(
        source="template_id",
        read_only=True,
        allow_null=True,
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
        certificate = kwargs.get("certificate")
        if certificate is None:
            certificate = self.context.get("certificate")

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
            queryset = CertificateTemplate.objects.filter(
                pk=template_id,
                certificate_type=certificate.certificate_type,
                is_active=True,
            )
            if school is not None:
                queryset = queryset.filter(school=school)

            if not queryset.exists():
                raise serializers.ValidationError(
                    {
                        "template_id": (
                            "No matching active certificate template "
                            "exists in your school."
                        )
                    }
                )

        return attrs

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
            return certificate_service.regenerate_certificate(
                previous=certificate,
                reason=self.validated_data["reason"],
                generated_by=request.user,
                template_id=self.validated_data.get("template_id"),
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _domain_error(exc) from exc


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


class CertificateTemplateSerializer(serializers.ModelSerializer):
    school_id = serializers.IntegerField(
        source="school_id",
        read_only=True,
    )
    created_by_id = serializers.IntegerField(
        source="created_by_id",
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

        certificate_type = attrs.get(
            "certificate_type",
            getattr(self.instance, "certificate_type", None),
        )
        version = getattr(self.instance, "version", None)

        queryset = CertificateTemplate.objects.filter(
            certificate_type=certificate_type,
        )

        if school is not None:
            queryset = queryset.filter(school=school)

        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if version is not None:
            queryset = queryset.filter(version=version)

        if queryset.exists():
            raise serializers.ValidationError(
                {
                    "certificate_type": (
                        "A certificate template with this type and "
                        "version already exists in your school."
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

        try:
            return certificate_service.create_template(
                school=school,
                certificate_type=validated_data["certificate_type"],
                layout_config=validated_data.get("layout_config", {}),
                signature_fields=validated_data.get(
                    "signature_fields",
                    [],
                ),
                is_active=validated_data.get("is_active", True),
                created_by=request.user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _domain_error(exc) from exc

    def update(
        self,
        instance: CertificateTemplate,
        validated_data: dict[str, Any],
    ) -> CertificateTemplate:
        request = _request_from_context(self)

        try:
            return certificate_service.update_template(
                template=instance,
                updated_by=request.user,
                changes=validated_data,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _domain_error(exc) from exc