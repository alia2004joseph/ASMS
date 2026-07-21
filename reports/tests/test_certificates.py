"""
Comprehensive tests for certificate models.

Expected model module:
    reports.models.certificates

Place this file at:
    reports/tests/test_certificates.py

Run:
    pytest reports/tests/test_certificates.py -q
"""

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from reports.constants import (
    ExportFormat,
    GeneratedReportStatus,
)
from reports.models.base import (
    AbstractGeneratedArtifact,
    AuditableModel,
    SchoolScopedManager,
    SchoolScopedModel,
    SchoolScopedQuerySet,
    VersionedModel,
    _generated_file_upload_path,
)
from reports.models.certificates import (
    Certificate,
    CertificateTemplate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def field(model, name):
    return model._meta.get_field(name)


def index_field_sets(model):
    return {tuple(index.fields) for index in model._meta.indexes}


def make_template(
    *,
    pk=101,
    school_id=11,
    certificate_type="COMPLETION",
    layout_config=None,
    signature_fields=None,
    is_active=True,
    version=1,
    created_by_id=None,
):
    obj = CertificateTemplate(
        school_id=school_id,
        certificate_type=certificate_type,
        layout_config={} if layout_config is None else layout_config,
        signature_fields={} if signature_fields is None else signature_fields,
        is_active=is_active,
        version=version,
        created_by_id=created_by_id,
    )
    obj.pk = pk
    return obj


def make_certificate(
    *,
    pk=201,
    school_id=11,
    student_id=31,
    template=None,
    template_id=None,
    certificate_type="COMPLETION",
    serial_number="CERT-001",
    verification_code="VERIFY-001",
    issued_by_id=None,
    issued_at=None,
    root_id=None,
    version=1,
    previous_version_id=None,
    is_latest=True,
    regeneration_reason="",
    is_revoked=False,
    revoked_reason="",
    revoked_at=None,
    revoked_by_id=None,
    file_hash="",
    file_size=None,
    mime_type="",
    export_format="",
    created_at=None,
    status=GeneratedReportStatus.PENDING,
    failure_message="",
):
    if template is None and template_id is None:
        template = make_template(
            school_id=school_id,
            certificate_type=certificate_type,
        )

    obj = Certificate(
        school_id=school_id,
        student_id=student_id,
        template=template,
        certificate_type=certificate_type,
        serial_number=serial_number,
        verification_code=verification_code,
        issued_by_id=issued_by_id,
        issued_at=issued_at,
        root_id=root_id or uuid.uuid4(),
        version=version,
        previous_version_id=previous_version_id,
        is_latest=is_latest,
        regeneration_reason=regeneration_reason,
        is_revoked=is_revoked,
        revoked_reason=revoked_reason,
        revoked_at=revoked_at,
        revoked_by_id=revoked_by_id,
        file_hash=file_hash,
        file_size=file_size,
        mime_type=mime_type,
        export_format=export_format,
        created_at=created_at,
        status=status,
        failure_message=failure_message,
    )
    if template is None:
        obj.template_id = template_id
    obj.pk = pk
    return obj


# ---------------------------------------------------------------------------
# CertificateTemplate tests
# ---------------------------------------------------------------------------


class TestCertificateTemplateInheritance:
    def test_inherits_school_scoped_model(self):
        assert issubclass(CertificateTemplate, SchoolScopedModel)

    def test_inherits_auditable_model(self):
        assert issubclass(CertificateTemplate, AuditableModel)

    def test_uses_school_scoped_manager(self):
        assert isinstance(CertificateTemplate.objects, SchoolScopedManager)

    def test_manager_queryset_type(self):
        assert isinstance(
            CertificateTemplate.objects.get_queryset(),
            SchoolScopedQuerySet,
        )


class TestCertificateTemplateConstants:
    def test_certificate_types_exact_values(self):
        assert CertificateTemplate.CERTIFICATE_TYPES == [
            ("COMPLETION", "Certificate of Completion"),
            ("PARTICIPATION", "Certificate of Participation"),
            ("GRADUATION", "Graduation Certificate"),
            ("TESTIMONIAL", "Testimonial"),
        ]

    @pytest.mark.parametrize(
        ("value", "label"),
        [
            ("COMPLETION", "Certificate of Completion"),
            ("PARTICIPATION", "Certificate of Participation"),
            ("GRADUATION", "Graduation Certificate"),
            ("TESTIMONIAL", "Testimonial"),
        ],
    )
    def test_each_certificate_type_pair(self, value, label):
        assert (value, label) in CertificateTemplate.CERTIFICATE_TYPES


class TestCertificateTemplateFields:
    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("school", models.ForeignKey),
            ("created_by", models.ForeignKey),
            ("created_at", models.DateTimeField),
            ("updated_at", models.DateTimeField),
            ("certificate_type", models.CharField),
            ("layout_config", models.JSONField),
            ("signature_fields", models.JSONField),
            ("is_active", models.BooleanField),
            ("version", models.PositiveIntegerField),
        ],
    )
    def test_field_types(self, name, expected_type):
        assert isinstance(field(CertificateTemplate, name), expected_type)

    def test_certificate_type_max_length(self):
        assert field(CertificateTemplate, "certificate_type").max_length == 20

    def test_certificate_type_choices(self):
        assert (
            list(field(CertificateTemplate, "certificate_type").choices)
            == CertificateTemplate.CERTIFICATE_TYPES
        )

    def test_layout_config_default(self):
        config = field(CertificateTemplate, "layout_config")
        assert config.default is dict
        assert config.blank is True

    def test_signature_fields_default(self):
        signature_fields = field(CertificateTemplate, "signature_fields")
        assert signature_fields.default is dict
        assert signature_fields.blank is True

    def test_signature_fields_help_text(self):
        help_text = field(
            CertificateTemplate,
            "signature_fields",
        ).help_text

        assert "Head Teacher" in help_text
        assert "Registrar" in help_text
        assert "primary" in help_text
        assert "secondary" in help_text

    def test_is_active_default(self):
        assert field(CertificateTemplate, "is_active").default is True

    def test_version_default(self):
        assert field(CertificateTemplate, "version").default == 1

    def test_school_uses_cascade(self):
        assert (
            field(CertificateTemplate, "school").remote_field.on_delete
            is models.CASCADE
        )

    def test_school_related_name(self):
        assert (
            field(CertificateTemplate, "school").remote_field.related_name
            == "+"
        )

    def test_created_by_is_optional(self):
        created_by = field(CertificateTemplate, "created_by")
        assert created_by.null is True
        assert created_by.blank is True

    def test_created_by_uses_set_null(self):
        assert (
            field(CertificateTemplate, "created_by").remote_field.on_delete
            is models.SET_NULL
        )

    def test_created_by_related_name(self):
        assert (
            field(CertificateTemplate, "created_by").remote_field.related_name
            == "+"
        )

    def test_created_at_is_not_editable(self):
        created_at = field(CertificateTemplate, "created_at")
        assert created_at.editable is False
        assert created_at.db_index is True

    def test_updated_at_uses_auto_now(self):
        assert field(CertificateTemplate, "updated_at").auto_now is True


class TestCertificateTemplateDefaults:
    def test_instance_defaults(self):
        obj = CertificateTemplate()

        assert obj.layout_config == {}
        assert obj.signature_fields == {}
        assert obj.is_active is True
        assert obj.version == 1

    def test_layout_config_defaults_are_not_shared(self):
        first = CertificateTemplate()
        second = CertificateTemplate()

        first.layout_config["title"] = "Completion"

        assert second.layout_config == {}

    def test_signature_field_defaults_are_not_shared(self):
        first = CertificateTemplate()
        second = CertificateTemplate()

        first.signature_fields["primary"] = "Head Teacher"

        assert second.signature_fields == {}

    def test_accepts_nested_layout_configuration(self):
        config = {
            "page": {"size": "A4", "orientation": "landscape"},
            "elements": [
                {"type": "text", "value": "Certificate"},
                {"type": "logo", "position": "top-center"},
            ],
        }

        obj = make_template(layout_config=config)

        assert obj.layout_config == config

    def test_accepts_multiple_signature_roles(self):
        signatures = {
            "primary": "Head Teacher",
            "secondary": "Registrar",
        }

        obj = make_template(signature_fields=signatures)

        assert obj.signature_fields == signatures


class TestCertificateTemplateMeta:
    def test_expected_index_exists(self):
        assert (
            "school",
            "certificate_type",
            "is_active",
        ) in index_field_sets(CertificateTemplate)

    def test_has_exact_index_count(self):
        assert len(CertificateTemplate._meta.indexes) == 1

    def test_has_no_custom_constraints(self):
        assert CertificateTemplate._meta.constraints == []


class TestCertificateTemplateString:
    @pytest.mark.parametrize(
        ("certificate_type", "label"),
        CertificateTemplate.CERTIFICATE_TYPES,
    )
    def test_string_for_each_certificate_type(
        self,
        certificate_type,
        label,
    ):
        obj = make_template(
            certificate_type=certificate_type,
            school_id=77,
        )

        assert str(obj) == f"{label} template (77)"

    def test_string_uses_raw_value_for_unknown_choice(self):
        obj = make_template(certificate_type="UNKNOWN", school_id=8)

        assert str(obj) == "UNKNOWN template (8)"

    def test_string_handles_missing_school_id(self):
        obj = CertificateTemplate(certificate_type="COMPLETION")

        assert str(obj) == "Certificate of Completion template (None)"


# ---------------------------------------------------------------------------
# Certificate tests
# ---------------------------------------------------------------------------


class TestCertificateInheritance:
    def test_inherits_generated_artifact(self):
        assert issubclass(Certificate, AbstractGeneratedArtifact)

    def test_inherits_versioned_model(self):
        assert issubclass(Certificate, VersionedModel)

    def test_inherits_school_scoped_model(self):
        assert issubclass(Certificate, SchoolScopedModel)

    def test_uses_school_scoped_manager(self):
        assert isinstance(Certificate.objects, SchoolScopedManager)

    def test_manager_queryset_type(self):
        assert isinstance(
            Certificate.objects.get_queryset(),
            SchoolScopedQuerySet,
        )


class TestCertificateFields:
    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("school", models.ForeignKey),
            ("file", models.FileField),
            ("file_hash", models.CharField),
            ("file_size", models.PositiveBigIntegerField),
            ("mime_type", models.CharField),
            ("export_format", models.CharField),
            ("created_at", models.DateTimeField),
            ("status", models.CharField),
            ("failure_message", models.TextField),
            ("root_id", models.UUIDField),
            ("version", models.PositiveIntegerField),
            ("previous_version", models.ForeignKey),
            ("is_latest", models.BooleanField),
            ("regeneration_reason", models.TextField),
            ("is_revoked", models.BooleanField),
            ("revoked_reason", models.TextField),
            ("revoked_at", models.DateTimeField),
            ("revoked_by", models.ForeignKey),
            ("student", models.ForeignKey),
            ("certificate_type", models.CharField),
            ("template", models.ForeignKey),
            ("serial_number", models.CharField),
            ("verification_code", models.CharField),
            ("issued_by", models.ForeignKey),
            ("issued_at", models.DateTimeField),
        ],
    )
    def test_field_types(self, name, expected_type):
        assert isinstance(field(Certificate, name), expected_type)

    def test_student_uses_cascade(self):
        assert (
            field(Certificate, "student").remote_field.on_delete
            is models.CASCADE
        )

    def test_student_related_name(self):
        assert (
            field(Certificate, "student").remote_field.related_name
            == "certificates"
        )

    def test_certificate_type_max_length(self):
        assert field(Certificate, "certificate_type").max_length == 20

    def test_certificate_type_choices(self):
        assert (
            list(field(Certificate, "certificate_type").choices)
            == CertificateTemplate.CERTIFICATE_TYPES
        )

    def test_template_uses_protect(self):
        assert (
            field(Certificate, "template").remote_field.on_delete
            is models.PROTECT
        )

    def test_template_related_name(self):
        assert (
            field(Certificate, "template").remote_field.related_name
            == "certificates"
        )

    @pytest.mark.parametrize(
        "name",
        ["serial_number", "verification_code"],
    )
    def test_identifier_field_metadata(self, name):
        identifier = field(Certificate, name)

        assert identifier.max_length == 64
        assert identifier.unique is True
        assert identifier.db_index is True

    def test_issued_by_is_optional(self):
        issued_by = field(Certificate, "issued_by")

        assert issued_by.null is True
        assert issued_by.blank is True

    def test_issued_by_uses_set_null(self):
        assert (
            field(Certificate, "issued_by").remote_field.on_delete
            is models.SET_NULL
        )

    def test_issued_by_related_name(self):
        assert (
            field(Certificate, "issued_by").remote_field.related_name
            == "+"
        )

    def test_issued_at_is_optional(self):
        issued_at = field(Certificate, "issued_at")

        assert issued_at.null is True
        assert issued_at.blank is True


class TestCertificateGeneratedArtifactFields:
    def test_file_is_optional(self):
        file_field = field(Certificate, "file")

        assert file_field.null is True
        assert file_field.blank is True

    def test_file_uses_generated_upload_path(self):
        assert field(Certificate, "file").upload_to is _generated_file_upload_path

    def test_file_hash_metadata(self):
        file_hash = field(Certificate, "file_hash")

        assert file_hash.max_length == 64
        assert file_hash.blank is True
        assert file_hash.default == ""
        assert file_hash.db_index is True

    def test_file_size_is_optional(self):
        file_size = field(Certificate, "file_size")

        assert file_size.null is True
        assert file_size.blank is True

    def test_mime_type_metadata(self):
        mime_type = field(Certificate, "mime_type")

        assert mime_type.max_length == 100
        assert mime_type.blank is True
        assert mime_type.default == ""

    def test_export_format_metadata(self):
        export_format = field(Certificate, "export_format")

        assert export_format.max_length == 10
        assert list(export_format.choices) == list(ExportFormat.choices)
        assert export_format.blank is True
        assert export_format.default == ""

    def test_artifact_created_at_is_optional(self):
        created_at = field(Certificate, "created_at")

        assert created_at.null is True
        assert created_at.blank is True

    def test_status_metadata(self):
        status = field(Certificate, "status")

        assert status.max_length == 20
        assert list(status.choices) == list(GeneratedReportStatus.choices)
        assert status.default == GeneratedReportStatus.PENDING
        assert status.db_index is True

    def test_failure_message_metadata(self):
        failure_message = field(Certificate, "failure_message")

        assert failure_message.blank is True
        assert failure_message.default == ""


class TestCertificateVersionFields:
    def test_root_id_default_is_uuid4(self):
        assert field(Certificate, "root_id").default is uuid.uuid4

    def test_root_id_is_not_editable_and_indexed(self):
        root_id = field(Certificate, "root_id")

        assert root_id.editable is False
        assert root_id.db_index is True

    def test_version_default(self):
        assert field(Certificate, "version").default == 1

    def test_previous_version_is_optional(self):
        previous = field(Certificate, "previous_version")

        assert previous.null is True
        assert previous.blank is True

    def test_previous_version_uses_set_null(self):
        assert (
            field(Certificate, "previous_version").remote_field.on_delete
            is models.SET_NULL
        )

    def test_previous_version_related_name(self):
        assert (
            field(Certificate, "previous_version").remote_field.related_name
            == "+"
        )

    def test_is_latest_default_and_index(self):
        is_latest = field(Certificate, "is_latest")

        assert is_latest.default is True
        assert is_latest.db_index is True

    def test_regeneration_reason_default(self):
        regeneration_reason = field(Certificate, "regeneration_reason")

        assert regeneration_reason.blank is True
        assert regeneration_reason.default == ""

    def test_is_revoked_default_and_index(self):
        is_revoked = field(Certificate, "is_revoked")

        assert is_revoked.default is False
        assert is_revoked.db_index is True

    def test_revoked_reason_default(self):
        revoked_reason = field(Certificate, "revoked_reason")

        assert revoked_reason.blank is True
        assert revoked_reason.default == ""

    def test_revoked_at_is_optional(self):
        revoked_at = field(Certificate, "revoked_at")

        assert revoked_at.null is True
        assert revoked_at.blank is True

    def test_revoked_by_is_optional(self):
        revoked_by = field(Certificate, "revoked_by")

        assert revoked_by.null is True
        assert revoked_by.blank is True

    def test_revoked_by_uses_set_null(self):
        assert (
            field(Certificate, "revoked_by").remote_field.on_delete
            is models.SET_NULL
        )

    def test_revoked_by_related_name(self):
        assert (
            field(Certificate, "revoked_by").remote_field.related_name
            == "+"
        )


class TestCertificateDefaults:
    def test_generated_artifact_defaults(self):
        certificate = Certificate()

        assert certificate.file_hash == ""
        assert certificate.file_size is None
        assert certificate.mime_type == ""
        assert certificate.export_format == ""
        assert certificate.created_at is None
        assert certificate.status == GeneratedReportStatus.PENDING
        assert certificate.failure_message == ""

    def test_version_defaults(self):
        certificate = Certificate()

        assert certificate.version == 1
        assert certificate.previous_version_id is None
        assert certificate.is_latest is True
        assert certificate.regeneration_reason == ""
        assert certificate.is_revoked is False
        assert certificate.revoked_reason == ""
        assert certificate.revoked_at is None
        assert certificate.revoked_by_id is None

    def test_root_ids_are_unique_by_default(self):
        first = Certificate()
        second = Certificate()

        assert first.root_id != second.root_id

    def test_root_id_is_uuid_instance(self):
        assert isinstance(Certificate().root_id, uuid.UUID)


class TestCertificateMeta:
    def test_student_type_index_exists(self):
        assert (
            "school",
            "student",
            "certificate_type",
        ) in index_field_sets(Certificate)

    def test_version_chain_index_exists(self):
        assert ("root_id", "version") in index_field_sets(Certificate)

    def test_exact_index_count(self):
        assert len(Certificate._meta.indexes) == 2

    def test_has_no_custom_constraints(self):
        assert Certificate._meta.constraints == []


class TestCertificateString:
    @pytest.mark.parametrize(
        "certificate_type",
        [
            "COMPLETION",
            "PARTICIPATION",
            "GRADUATION",
            "TESTIMONIAL",
        ],
    )
    def test_string_for_each_certificate_type(self, certificate_type):
        certificate = make_certificate(
            certificate_type=certificate_type,
            serial_number="SERIAL-123",
        )

        assert (
            str(certificate)
            == f"{certificate_type} certificate #SERIAL-123"
        )

    def test_string_uses_raw_certificate_type(self):
        certificate = make_certificate(
            certificate_type="CUSTOM",
            serial_number="CUSTOM-1",
        )

        assert str(certificate) == "CUSTOM certificate #CUSTOM-1"

    def test_string_handles_empty_serial_number(self):
        certificate = make_certificate(serial_number="")

        assert str(certificate) == "COMPLETION certificate #"


class TestCertificateVersionValidation:
    def test_non_revoked_certificate_is_valid_without_revocation_data(self):
        certificate = make_certificate(
            is_revoked=False,
            revoked_reason="",
            revoked_at=None,
        )

        certificate.clean()

    def test_revoked_certificate_with_all_required_data_is_valid(self):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason="Incorrect student details",
            revoked_at=timezone.now(),
        )

        certificate.clean()

    @pytest.mark.parametrize("reason", ["", " ", "   ", "\n\t"])
    def test_revoked_certificate_requires_non_blank_reason(self, reason):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason=reason,
            revoked_at=timezone.now(),
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict[
            "revoked_reason"
        ] == ["A revocation reason is required."]

    def test_revoked_certificate_requires_timestamp(self):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason="Duplicate certificate",
            revoked_at=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict[
            "revoked_at"
        ] == ["A revocation timestamp is required."]

    def test_revoked_certificate_collects_both_errors(self):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason="",
            revoked_at=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "revoked_reason": ["A revocation reason is required."],
            "revoked_at": ["A revocation timestamp is required."],
        }


class TestGeneratedFileUploadPathForCertificate:
    def test_uses_certificate_class_name_when_document_type_missing(self):
        certificate = make_certificate(school_id=44)

        path = _generated_file_upload_path(
            certificate,
            "original.PDF",
        )

        assert path.startswith("reports/44/certificate/")
        assert path.endswith(".pdf")

    def test_hides_original_filename(self):
        certificate = make_certificate()

        path = _generated_file_upload_path(
            certificate,
            "student-secret-name.pdf",
        )

        assert "student-secret-name" not in path

    def test_uses_uuid_filename(self):
        import uuid

        fake = type("FakeUUID", (), {"hex": "b" * 32})()

        certificate = make_certificate(
            school_id=12,
            root_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        )

        with patch(
            "reports.models.base.uuid.uuid4",
            return_value=fake,
        ) as mocked:
            path = _generated_file_upload_path(
                certificate,
                "certificate.pdf",
            )

        mocked.assert_called_once_with()

        assert path == (
            f"reports/12/certificate/{'b'*32}.pdf"
        )

    @pytest.mark.parametrize(
        ("filename", "suffix"),
        [
            ("document.PDF", ".pdf"),
            ("document.DocX", ".docx"),
            ("document.zip", ".zip"),
            ("document", ""),
        ],
    )
    def test_extension_is_lowercased(self, filename, suffix):
        path = _generated_file_upload_path(
            make_certificate(),
            filename,
        )

        assert path.endswith(suffix)

    def test_paths_are_unique(self):
        certificate = make_certificate()

        first = _generated_file_upload_path(
            certificate,
            "certificate.pdf",
        )
        second = _generated_file_upload_path(
            certificate,
            "certificate.pdf",
        )

        assert first != second


class TestCertificateChoiceDisplays:
    @pytest.mark.parametrize(
        ("value", "label"),
        CertificateTemplate.CERTIFICATE_TYPES,
    )
    def test_template_choice_display(self, value, label):
        template = make_template(certificate_type=value)

        assert template.get_certificate_type_display() == label

    @pytest.mark.parametrize(
        ("value", "label"),
        CertificateTemplate.CERTIFICATE_TYPES,
    )
    def test_certificate_choice_display(self, value, label):
        certificate = make_certificate(certificate_type=value)

        assert certificate.get_certificate_type_display() == label


class TestCertificateArtifactChoices:
    @pytest.mark.parametrize(
        "export_format",
        [
            "",
            ExportFormat.PDF,
            ExportFormat.EXCEL,
            ExportFormat.CSV,
            ExportFormat.ZIP,
        ],
    )
    def test_accepts_export_format_choice(self, export_format):
        certificate = make_certificate(export_format=export_format)

        assert certificate.export_format == export_format

    @pytest.mark.parametrize(
        "status",
        [
            GeneratedReportStatus.PENDING,
            GeneratedReportStatus.PROCESSING,
            GeneratedReportStatus.READY,
            GeneratedReportStatus.FAILED,
        ],
    )
    def test_accepts_status_choice(self, status):
        certificate = make_certificate(status=status)

        assert certificate.status == status