"""
Tests for certificate serializers aligned with the current certificate service.

Run:
    pytest reports/tests/test_certificate_serializers.py -q
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from reports.constants import VerificationResult
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.certificates import Certificate, CertificateTemplate
from reports.serializers import certificate_serializers as serializer_module
from reports.serializers.certificate_serializers import (
    CertificateIssueRequestSerializer,
    CertificateRegenerateRequestSerializer,
    CertificateRevokeRequestSerializer,
    CertificateSerializer,
    CertificateTemplateSerializer,
    CertificateVerifyResponseSerializer,
    _domain_error,
    _request_from_context,
    _request_school,
)


def first_certificate_type():
    return CertificateTemplate.CERTIFICATE_TYPES[0][0]


def first_verification_result():
    return VerificationResult.choices[0][0]


def make_user(*, school=None, is_superuser=False):
    return SimpleNamespace(
        school=school,
        is_superuser=is_superuser,
    )


def make_request(*, user=None):
    return SimpleNamespace(
        user=user or make_user(
            school=SimpleNamespace(pk=1)
        ),
        build_absolute_uri=lambda url: f"https://example.test{url}",
    )


def make_certificate(**overrides):
    values = {
        "id": 1,
        "student_id": 10,
        "certificate_type": first_certificate_type(),
        "template_id": None,
        "serial_number": "CERT-001",
        "verification_code": "VERIFY-001",
        "version": 1,
        "root_id": None,
        "previous_version_id": None,
        "is_latest": True,
        "is_revoked": False,
        "revoked_reason": "",
        "revoked_at": None,
        "revoked_by_id": None,
        "regeneration_reason": "",
        "issued_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "issued_by_id": 4,
        "status": "READY",
        "file": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_template(**overrides):
    values = {
        "id": 1,
        "school_id": 7,
        "certificate_type": first_certificate_type(),
        "layout_config": {},
        "signature_fields": [],
        "is_active": True,
        "version": 1,
        "created_by_id": 9,
        "pk": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestHelpers:
    def test_request_from_context(self):
        request = make_request()
        serializer = serializers.Serializer(
            context={"request": request}
        )
        assert _request_from_context(serializer) is request

    def test_missing_request(self):
        serializer = serializers.Serializer()
        with pytest.raises(serializers.ValidationError):
            _request_from_context(serializer)

    def test_request_school(self):
        school = SimpleNamespace(pk=2)
        serializer = serializers.Serializer(
            context={
                "request": make_request(
                    user=make_user(school=school)
                )
            }
        )
        assert _request_school(serializer) is school

    def test_non_superuser_requires_school(self):
        serializer = serializers.Serializer(
            context={
                "request": make_request(
                    user=make_user(
                        school=None,
                        is_superuser=False,
                    )
                )
            }
        )
        with pytest.raises(serializers.ValidationError):
            _request_school(serializer)

    def test_superuser_without_school(self):
        serializer = serializers.Serializer(
            context={
                "request": make_request(
                    user=make_user(
                        school=None,
                        is_superuser=True,
                    )
                )
            }
        )
        assert _request_school(serializer) is None

    def test_domain_error(self):
        assert _domain_error(
            ValueError("failure")
        ).detail == ["failure"]


class TestCertificateIssueRequestSerializer:
    def test_fields(self):
        assert tuple(
            CertificateIssueRequestSerializer().fields
        ) == (
            "student_id",
            "certificate_type",
            "template_id",
        )

    def test_invalid_student_id(self):
        serializer = CertificateIssueRequestSerializer(
            data={
                "student_id": 0,
                "certificate_type": first_certificate_type(),
            },
            context={"request": make_request()},
        )
        assert not serializer.is_valid()

    def test_student_not_found(self, monkeypatch):
        school = SimpleNamespace(pk=1)
        student_model = Mock()
        student_model.DoesNotExist = type(
            "StudentDoesNotExist",
            (Exception,),
            {},
        )
        student_model.objects.get.side_effect = (
            student_model.DoesNotExist()
        )

        monkeypatch.setattr(
            serializer_module,
            "_student_model",
            Mock(return_value=student_model),
        )

        serializer = CertificateIssueRequestSerializer(
            data={
                "student_id": 5,
                "certificate_type": first_certificate_type(),
            },
            context={
                "request": make_request(
                    user=make_user(school=school)
                )
            },
        )

        assert not serializer.is_valid()
        assert "student_id" in serializer.errors

    def test_valid_request_and_create(
        self,
        monkeypatch,
    ):
        school = SimpleNamespace(pk=1)
        user = make_user(school=school)
        student = SimpleNamespace(pk=5, school=school)
        student_model = Mock()
        student_model.objects.get.return_value = student

        monkeypatch.setattr(
            serializer_module,
            "_student_model",
            Mock(return_value=student_model),
        )

        certificate = make_certificate()
        issue_mock = Mock(return_value=certificate)
        monkeypatch.setattr(
            serializer_module.certificate_service,
            "issue_certificate",
            issue_mock,
        )

        serializer = CertificateIssueRequestSerializer(
            data={
                "student_id": 5,
                "certificate_type": first_certificate_type(),
            },
            context={
                "request": make_request(user=user)
            },
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.save() is certificate

        issue_mock.assert_called_once_with(
            student=student,
            school=school,
            certificate_type=first_certificate_type(),
            issued_by=user,
            template=None,
        )

    def test_template_is_resolved(
        self,
        monkeypatch,
    ):
        school = SimpleNamespace(pk=1)
        student = SimpleNamespace(pk=5)
        template = make_template()

        student_model = Mock()
        student_model.objects.get.return_value = student

        monkeypatch.setattr(
            serializer_module,
            "_student_model",
            Mock(return_value=student_model),
        )
        monkeypatch.setattr(
            serializer_module.CertificateTemplate.objects,
            "get",
            Mock(return_value=template),
        )
        monkeypatch.setattr(
            serializer_module.certificate_service,
            "issue_certificate",
            Mock(return_value=make_certificate()),
        )

        serializer = CertificateIssueRequestSerializer(
            data={
                "student_id": 5,
                "certificate_type": first_certificate_type(),
                "template_id": 9,
            },
            context={
                "request": make_request(
                    user=make_user(school=school)
                )
            },
        )

        assert serializer.is_valid(), serializer.errors
        serializer.save()

        assert (
            serializer_module.certificate_service
            .issue_certificate.call_args.kwargs["template"]
            is template
        )

    @pytest.mark.parametrize(
        "error",
        [
            DomainValidationError("failure"),
            DjangoValidationError("failure"),
        ],
    )
    def test_create_converts_known_errors(
        self,
        monkeypatch,
        error,
    ):
        school = SimpleNamespace(pk=1)
        student_model = Mock()
        student_model.objects.get.return_value = (
            SimpleNamespace(pk=5)
        )

        monkeypatch.setattr(
            serializer_module,
            "_student_model",
            Mock(return_value=student_model),
        )
        monkeypatch.setattr(
            serializer_module.certificate_service,
            "issue_certificate",
            Mock(side_effect=error),
        )

        serializer = CertificateIssueRequestSerializer(
            data={
                "student_id": 5,
                "certificate_type": first_certificate_type(),
            },
            context={
                "request": make_request(
                    user=make_user(school=school)
                )
            },
        )

        assert serializer.is_valid(), serializer.errors

        with pytest.raises(serializers.ValidationError):
            serializer.save()


class TestCertificateSerializer:
    def test_all_fields_read_only(self):
        serializer = CertificateSerializer(
            data={
                "id": 10,
                "student_id": 20,
                "status": "REVOKED",
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {}

    def test_file_url_none(self):
        assert CertificateSerializer().get_file_url(
            make_certificate(file=None)
        ) is None

    def test_relative_file_url(self):
        obj = make_certificate(
            file=SimpleNamespace(url="/media/cert.pdf")
        )
        assert CertificateSerializer().get_file_url(
            obj
        ) == "/media/cert.pdf"

    def test_absolute_file_url(self):
        obj = make_certificate(
            file=SimpleNamespace(url="/media/cert.pdf")
        )
        serializer = CertificateSerializer(
            context={"request": make_request()}
        )
        assert serializer.get_file_url(
            obj
        ) == "https://example.test/media/cert.pdf"


class TestCertificateRevokeRequestSerializer:
    def test_reason_trimmed(self):
        serializer = CertificateRevokeRequestSerializer(
            data={"reason": "  Invalid data  "},
            context={"request": make_request()},
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["reason"] == (
            "Invalid data"
        )

    def test_certificate_required(self):
        serializer = CertificateRevokeRequestSerializer(
            data={"reason": "Valid reason"},
            context={"request": make_request()},
        )
        assert serializer.is_valid(), serializer.errors

        with pytest.raises(serializers.ValidationError):
            serializer.save()

    def test_revoke_delegates_to_service(
        self,
        monkeypatch,
    ):
        certificate = make_certificate()
        user = make_user(school=SimpleNamespace(pk=1))
        revoke_mock = Mock(return_value=certificate)

        monkeypatch.setattr(
            serializer_module.certificate_service,
            "revoke_certificate",
            revoke_mock,
        )

        serializer = CertificateRevokeRequestSerializer(
            data={"reason": "Valid reason"},
            context={
                "request": make_request(user=user),
                "certificate": certificate,
            },
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.save() is certificate

        revoke_mock.assert_called_once_with(
            certificate=certificate,
            reason="Valid reason",
            revoked_by=user,
        )


class TestCertificateRegenerateRequestSerializer:
    def test_context_required(self):
        serializer = CertificateRegenerateRequestSerializer(
            data={"reason": "Valid reason"},
            context={"request": make_request()},
        )
        assert not serializer.is_valid()

    def test_save_fails_explicitly(self):
        serializer = CertificateRegenerateRequestSerializer(
            data={"reason": "Valid reason"},
            context={
                "request": make_request(),
                "certificate": make_certificate(),
            },
        )

        assert serializer.is_valid(), serializer.errors

        with pytest.raises(
            serializers.ValidationError,
            match="regeneration is not available",
        ):
            serializer.save()


class TestVerifyResponseSerializer:
    def test_minimum_payload(self):
        serializer = CertificateVerifyResponseSerializer(
            data={"result": first_verification_result()}
        )
        assert serializer.is_valid(), serializer.errors

    def test_student_name_supported(self):
        serializer = CertificateVerifyResponseSerializer(
            data={
                "result": first_verification_result(),
                "student_name": "ALIA Joseph",
            }
        )
        assert serializer.is_valid(), serializer.errors

    def test_invalid_result(self):
        serializer = CertificateVerifyResponseSerializer(
            data={"result": "INVALID"}
        )
        assert not serializer.is_valid()


class TestCertificateTemplateSerializer:
    @pytest.mark.parametrize(
        "value",
        [[], "{}", 1, True, None],
    )
    def test_layout_config_object_required(self, value):
        serializer = CertificateTemplateSerializer()

        with pytest.raises(serializers.ValidationError):
            serializer.validate_layout_config(value)

    @pytest.mark.parametrize(
        "value",
        ["field", 1, True, None],
    )
    def test_signature_fields_array_or_object_required(
        self,
        value,
    ):
        serializer = CertificateTemplateSerializer()

        with pytest.raises(serializers.ValidationError):
            serializer.validate_signature_fields(value)

    def test_create_uses_model_manager(
        self,
        monkeypatch,
    ):
        school = SimpleNamespace(pk=1)
        user = make_user(school=school)
        template = make_template()

        create_mock = Mock(return_value=template)
        monkeypatch.setattr(
            serializer_module.CertificateTemplate.objects,
            "create",
            create_mock,
        )

        serializer = CertificateTemplateSerializer(
            context={
                "request": make_request(user=user)
            }
        )

        result = serializer.create(
            {
                "certificate_type": first_certificate_type(),
                "layout_config": {},
                "signature_fields": [],
                "is_active": True,
            }
        )

        assert result is template
        create_mock.assert_called_once_with(
            school=school,
            created_by=user,
            certificate_type=first_certificate_type(),
            layout_config={},
            signature_fields=[],
            is_active=True,
        )

    def test_update_sets_fields_and_saves(self):
        instance = Mock()
        instance.layout_config = {}
        instance.is_active = True

        serializer = CertificateTemplateSerializer()
        result = serializer.update(
            instance,
            {
                "layout_config": {"updated": True},
                "is_active": False,
            },
        )

        assert result is instance
        assert instance.layout_config == {"updated": True}
        assert instance.is_active is False
        instance.full_clean.assert_called_once_with()
        instance.save.assert_called_once_with()