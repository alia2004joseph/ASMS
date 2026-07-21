import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from reports.constants import GeneratedReportStatus
from reports.models.base import (
    AbstractGeneratedArtifact,
    AuditableModel,
    SchoolScopedModel,
    SchoolScopedQuerySet,
    VersionedModel,
    _generated_file_upload_path,
)


# Concrete test models are needed because the production base models are abstract.
class DummySchoolScopedRecord(SchoolScopedModel):
    class Meta:
        app_label = "reports_tests"


class DummyAuditableRecord(AuditableModel):
    class Meta:
        app_label = "reports_tests"


class DummyVersionedRecord(VersionedModel):
    class Meta:
        app_label = "reports_tests"


class DummyGeneratedArtifact(AbstractGeneratedArtifact):
    document_type = "RESULT_SLIP"

    class Meta:
        app_label = "reports_tests"


class TestSchoolScopedQuerySet:
    def test_for_school_rejects_none(self):
        queryset = SchoolScopedQuerySet(
            model=DummySchoolScopedRecord,
            using="default",
        )

        with pytest.raises(
            ValueError,
            match=r"requires a concrete school",
        ):
            queryset.for_school(None)

    def test_for_school_filters_using_school(self):
        queryset = SchoolScopedQuerySet(
            model=DummySchoolScopedRecord,
            using="default",
        )
        school = MagicMock(name="school")
        expected_queryset = MagicMock(name="filtered_queryset")

        with patch.object(
            queryset,
            "filter",
            return_value=expected_queryset,
        ) as filter_mock:
            result = queryset.for_school(school)

        filter_mock.assert_called_once_with(school=school)
        assert result is expected_queryset

    def test_school_scoped_model_uses_custom_manager(self):
        manager = DummySchoolScopedRecord.objects

        assert manager is not None
        assert hasattr(manager, "for_school")


class TestAuditableModel:
    def test_created_at_is_populated_on_initialization(self):
        before = timezone.now()

        record = DummyAuditableRecord()

        after = timezone.now()

        assert record.created_at is not None
        assert before <= record.created_at <= after

    def test_created_by_is_optional(self):
        record = DummyAuditableRecord()

        assert record.created_by is None
        assert record.created_by_id is None


class TestVersionedModel:
    def test_default_versioning_values(self):
        record = DummyVersionedRecord()

        assert record.root_id is not None
        assert record.version == 1
        assert record.previous_version is None
        assert record.is_latest is True
        assert record.regeneration_reason == ""
        assert record.is_revoked is False
        assert record.revoked_reason == ""
        assert record.revoked_at is None
        assert record.revoked_by is None

    def test_new_records_receive_different_root_ids(self):
        first = DummyVersionedRecord()
        second = DummyVersionedRecord()

        assert first.root_id != second.root_id

    def test_revoked_record_requires_reason(self):
        record = DummyVersionedRecord(
            is_revoked=True,
            revoked_reason="",
            revoked_at=timezone.now(),
        )

        with pytest.raises(ValidationError) as exc_info:
            record.clean()

        assert "revoked_reason" in exc_info.value.message_dict

    def test_revoked_record_rejects_whitespace_only_reason(self):
        record = DummyVersionedRecord(
            is_revoked=True,
            revoked_reason="   ",
            revoked_at=timezone.now(),
        )

        with pytest.raises(ValidationError) as exc_info:
            record.clean()

        assert "revoked_reason" in exc_info.value.message_dict

    def test_revoked_record_requires_timestamp(self):
        record = DummyVersionedRecord(
            is_revoked=True,
            revoked_reason="Issued in error",
            revoked_at=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            record.clean()

        assert "revoked_at" in exc_info.value.message_dict

    def test_revoked_record_requires_reason_and_timestamp(self):
        record = DummyVersionedRecord(
            is_revoked=True,
            revoked_reason="",
            revoked_at=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            record.clean()

        errors = exc_info.value.message_dict

        assert "revoked_reason" in errors
        assert "revoked_at" in errors

    def test_valid_revoked_record_passes_clean(self):
        record = DummyVersionedRecord(
            is_revoked=True,
            revoked_reason="The document contained incorrect information.",
            revoked_at=timezone.now(),
        )

        # clean() returns None when validation succeeds.
        assert record.clean() is None

    def test_non_revoked_record_does_not_require_revocation_metadata(self):
        record = DummyVersionedRecord(
            is_revoked=False,
            revoked_reason="",
            revoked_at=None,
        )

        assert record.clean() is None


class TestGeneratedFileUploadPath:
    def test_path_contains_school_and_document_type(self):
        instance = SimpleNamespace(
            school_id=25,
            document_type="RESULT_SLIP",
        )

        path = _generated_file_upload_path(
            instance,
            "Student-Result.PDF",
        )

        assert path.startswith("reports/25/result_slip/")
        assert path.endswith(".pdf")

    def test_path_uses_random_hex_filename(self):
        instance = SimpleNamespace(
            school_id=7,
            document_type="TRANSCRIPT",
        )

        path = _generated_file_upload_path(instance, "report.pdf")
        filename = path.rsplit("/", 1)[-1]

        assert re.fullmatch(r"[0-9a-f]{32}\.pdf", filename)

    def test_generated_paths_are_unique(self):
        instance = SimpleNamespace(
            school_id=7,
            document_type="TRANSCRIPT",
        )

        first_path = _generated_file_upload_path(instance, "report.pdf")
        second_path = _generated_file_upload_path(instance, "report.pdf")

        assert first_path != second_path

    def test_extension_is_converted_to_lowercase(self):
        instance = SimpleNamespace(
            school_id=10,
            document_type="CERTIFICATE",
        )

        path = _generated_file_upload_path(instance, "Certificate.PDF")

        assert path.endswith(".pdf")

    def test_instance_class_name_is_used_when_document_type_is_missing(self):
        class ResultDocument:
            school_id = 4

        path = _generated_file_upload_path(
            ResultDocument(),
            "result.csv",
        )

        assert path.startswith("reports/4/resultdocument/")
        assert path.endswith(".csv")

    def test_unscoped_value_is_used_when_school_id_is_missing(self):
        instance = SimpleNamespace(document_type="EXPORT")

        path = _generated_file_upload_path(instance, "data.xlsx")

        assert path.startswith("reports/unscoped/export/")


class TestAbstractGeneratedArtifact:
    def test_default_artifact_values(self):
        artifact = DummyGeneratedArtifact()

        assert not artifact.file
        assert artifact.file_hash == ""
        assert artifact.file_size is None
        assert artifact.mime_type == ""
        assert artifact.export_format == ""
        assert artifact.created_at is None
        assert artifact.status == GeneratedReportStatus.PENDING
        assert artifact.failure_message == ""

    def test_artifact_accepts_generation_failure_information(self):
        artifact = DummyGeneratedArtifact(
            status=GeneratedReportStatus.FAILED,
            failure_message="PDF generation failed.",
        )

        assert artifact.status == GeneratedReportStatus.FAILED
        assert artifact.failure_message == "PDF generation failed."