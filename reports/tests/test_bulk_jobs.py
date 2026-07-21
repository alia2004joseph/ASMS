"""Comprehensive tests for reports/models/bulk_reports.py.

Run:
    pytest reports/tests/test_bulk_jobs.py -q

If the source module uses another filename, update the import below.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from reports.constants import (
    BulkItemStatus,
    BulkJobStatus,
    BulkJobType,
    ExportFormat,
    GeneratedReportStatus,
)
from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedManager,
    SchoolScopedModel,
    SchoolScopedQuerySet,
    _generated_file_upload_path,
)
from reports.models.bulk_jobs import (
    BulkExportArchive,
    BulkReportItem,
    BulkReportJob,
    _archive_upload_path,
)


HEX_32 = re.compile(r"^[0-9a-f]{32}$")


def model_field(model, name):
    return model._meta.get_field(name)


def make_job(**overrides):
    values = {
        "school_id": 11,
        "job_type": BulkJobType.REPORT_CARDS,
        "status": BulkJobStatus.PENDING,
        "parameters": {},
        "total_items": 0,
        "completed_items": 0,
        "failed_items": 0,
    }
    values.update(overrides)
    obj = BulkReportJob(**values)
    obj.pk = values.pop("pk", 101) if "pk" in values else 101
    return obj


def make_item(**overrides):
    job = overrides.pop("job", None)
    job_id = overrides.pop("job_id", None)
    values = {
        "target_content_type_id": 1,
        "target_object_id": 99,
        "status": BulkItemStatus.PENDING,
        "error_message": "",
    }
    values.update(overrides)
    obj = BulkReportItem(**values)
    if job is not None:
        obj.job = job
    else:
        obj.job_id = 101 if job_id is None else job_id
    obj.pk = 201
    return obj


def make_archive(**overrides):
    job = overrides.pop("job", None)
    job_id = overrides.pop("job_id", None)
    values = {
        "school_id": 11,
        "manifest": {},
        "downloaded_count": 0,
        "file_hash": "",
        "file_size": None,
        "mime_type": "",
        "export_format": "",
        "status": GeneratedReportStatus.PENDING,
        "failure_message": "",
    }
    values.update(overrides)
    obj = BulkExportArchive(**values)
    if job is not None:
        obj.job = job
    else:
        obj.job_id = 101 if job_id is None else job_id
    obj.pk = 301
    return obj


class TestArchiveUploadPath:
    def test_uses_school_directory(self):
        path = _archive_upload_path(make_archive(school_id=77), "archive.zip")
        assert path.startswith("reports/77/bulk_archives/")

    @pytest.mark.parametrize(
        ("filename", "suffix"),
        [
            ("archive.zip", ".zip"),
            ("ARCHIVE.ZIP", ".zip"),
            ("bundle.Tar.GZ", ".gz"),
            ("results.csv", ".csv"),
        ],
    )
    def test_normalizes_extension(self, filename, suffix):
        assert _archive_upload_path(make_archive(), filename).endswith(suffix)

    @pytest.mark.parametrize("filename", ["archive", "no_suffix", ""])
    def test_defaults_to_zip_without_extension(self, filename):
        assert _archive_upload_path(make_archive(), filename).endswith(".zip")

    def test_hides_original_filename(self):
        path = _archive_upload_path(make_archive(), "secret-results.zip")
        assert "secret-results" not in path

    def test_uses_uuid_hex_filename(self):
        path = _archive_upload_path(make_archive(), "archive.zip")
        assert HEX_32.fullmatch(Path(path).stem)

    def test_generates_unique_paths(self):
        obj = make_archive()
        assert _archive_upload_path(obj, "a.zip") != _archive_upload_path(obj, "a.zip")

    def test_calls_uuid_once(self):
        fake = type("FakeUUID", (), {"hex": "a" * 32})()
        with patch("reports.models.bulk_jobs.uuid.uuid4", return_value=fake) as mocked:
            path = _archive_upload_path(make_archive(), "a.zip")
        mocked.assert_called_once_with()
        assert path.endswith(f"{'a' * 32}.zip")



class TestBulkReportJobFields:
    def test_inherits_school_scoped_model(self):
        assert issubclass(BulkReportJob, SchoolScopedModel)

    def test_uses_school_scoped_manager(self):
        assert isinstance(BulkReportJob.objects, SchoolScopedManager)
        assert isinstance(BulkReportJob.objects.get_queryset(), SchoolScopedQuerySet)

    @pytest.mark.parametrize(
        ("name", "field_type"),
        [
            ("school", models.ForeignKey),
            ("job_type", models.CharField),
            ("requested_by", models.ForeignKey),
            ("parameters", models.JSONField),
            ("status", models.CharField),
            ("total_items", models.PositiveIntegerField),
            ("completed_items", models.PositiveIntegerField),
            ("failed_items", models.PositiveIntegerField),
            ("started_at", models.DateTimeField),
            ("finished_at", models.DateTimeField),
            ("created_at", models.DateTimeField),
        ],
    )
    def test_field_types(self, name, field_type):
        assert isinstance(model_field(BulkReportJob, name), field_type)

    def test_job_type_configuration(self):
        field = model_field(BulkReportJob, "job_type")
        assert field.max_length == 30
        assert list(field.choices) == list(BulkJobType.choices)
        assert field.db_index is True

    def test_status_configuration(self):
        field = model_field(BulkReportJob, "status")
        assert field.max_length == 20
        assert list(field.choices) == list(BulkJobStatus.choices)
        assert field.default == BulkJobStatus.PENDING
        assert field.db_index is True

    def test_requested_by_configuration(self):
        field = model_field(BulkReportJob, "requested_by")
        assert field.null is True and field.blank is True
        assert field.remote_field.on_delete is models.SET_NULL
        assert field.remote_field.related_name == "bulk_report_jobs"

    def test_parameters_configuration(self):
        field = model_field(BulkReportJob, "parameters")
        assert field.default is dict
        assert field.blank is True

    def test_parameter_defaults_are_independent(self):
        first, second = BulkReportJob(), BulkReportJob()
        first.parameters["term"] = 1
        assert second.parameters == {}

    @pytest.mark.parametrize("name", ["total_items", "completed_items", "failed_items"])
    def test_counter_default(self, name):
        assert model_field(BulkReportJob, name).default == 0

    @pytest.mark.parametrize("name", ["started_at", "finished_at"])
    def test_processing_timestamp_is_optional(self, name):
        field = model_field(BulkReportJob, name)
        assert field.null is True and field.blank is True

    def test_created_at_configuration(self):
        field = model_field(BulkReportJob, "created_at")
        assert field.auto_now_add is True
        assert field.db_index is True


class TestBulkReportJobMeta:
    def test_ordering(self):
        assert BulkReportJob._meta.ordering == ["-created_at", "-pk"]

    @pytest.mark.parametrize(
        "name",
        [
            "bulk_job_total_non_negative",
            "bulk_job_completed_non_negative",
            "bulk_job_failed_non_negative",
            "bulk_job_progress_valid",
        ],
    )
    def test_constraint_exists(self, name):
        assert name in {c.name for c in BulkReportJob._meta.constraints}

    def test_constraint_count(self):
        assert len(BulkReportJob._meta.constraints) == 4

    @pytest.mark.parametrize(
        ("name", "condition"),
        [
            ("bulk_job_total_non_negative", Q(total_items__gte=0)),
            ("bulk_job_completed_non_negative", Q(completed_items__gte=0)),
            ("bulk_job_failed_non_negative", Q(failed_items__gte=0)),
            (
                "bulk_job_progress_valid",
                Q(completed_items__lte=F("total_items") - F("failed_items")),
            ),
        ],
    )
    def test_constraint_definition(self, name, condition):
        constraint = next(c for c in BulkReportJob._meta.constraints if c.name == name)
        assert isinstance(constraint, models.CheckConstraint)
        assert constraint.condition == condition

    @pytest.mark.parametrize(
        ("name", "fields"),
        [
            ("bulk_job_status_idx", ["school", "status", "-created_at"]),
            ("bulk_job_type_idx", ["school", "job_type"]),
            ("bulk_job_requester_idx", ["requested_by", "-created_at"]),
        ],
    )
    def test_index_definition(self, name, fields):
        index = next(i for i in BulkReportJob._meta.indexes if i.name == name)
        assert index.fields == fields


class TestBulkReportJobBehavior:
    @pytest.mark.parametrize(
        ("total", "completed", "failed"),
        [(0, 0, 0), (1, 1, 0), (1, 0, 1), (10, 4, 3), (10, 6, 4)],
    )
    def test_clean_accepts_valid_progress(self, total, completed, failed):
        make_job(
            total_items=total,
            completed_items=completed,
            failed_items=failed,
        ).clean()

    @pytest.mark.parametrize(
        ("total", "completed", "failed"),
        [(0, 1, 0), (0, 0, 1), (1, 1, 1), (5, 6, 0), (10, 7, 4)],
    )
    def test_clean_rejects_invalid_progress(self, total, completed, failed):
        job = make_job(
            total_items=total,
            completed_items=completed,
            failed_items=failed,
        )
        with pytest.raises(ValidationError, match="cannot exceed total items"):
            job.clean()

    @pytest.mark.parametrize(
        ("total", "completed", "failed", "expected"),
        [
            (0, 0, 0, 0),
            (1, 0, 0, 0.0),
            (1, 1, 0, 100.0),
            (1, 0, 1, 100.0),
            (2, 1, 0, 50.0),
            (4, 2, 1, 75.0),
            (3, 1, 0, 33.33),
            (3, 1, 1, 66.67),
            (8, 3, 2, 62.5),
        ],
    )
    def test_progress_percentage(self, total, completed, failed, expected):
        job = make_job(
            total_items=total,
            completed_items=completed,
            failed_items=failed,
        )
        assert job.progress_percentage == expected

    @pytest.mark.parametrize(
        ("job_type", "label"),
        [
            (BulkJobType.REPORT_CARDS, "Report Cards"),
            (BulkJobType.RESULT_SLIPS, "Result Slips"),
            (BulkJobType.PERMITS, "Examination Permits"),
            (BulkJobType.ID_CARDS, "ID Cards"),
            (BulkJobType.FEE_CLEARANCE, "Fee Clearance Certificates"),
            (BulkJobType.CUSTOM, "Custom Report"),
        ],
    )
    def test_string(self, job_type, label):
        job = make_job(job_type=job_type, completed_items=3, total_items=10)
        assert str(job) == f"{label} (3/10)"


class TestBulkReportItem:
    @pytest.mark.parametrize(
        ("name", "field_type"),
        [
            ("job", models.ForeignKey),
            ("target_content_type", models.ForeignKey),
            ("target_object_id", models.PositiveBigIntegerField),
            ("status", models.CharField),
            ("generated_report", models.ForeignKey),
            ("error_message", models.TextField),
        ],
    )
    def test_field_types(self, name, field_type):
        assert isinstance(model_field(BulkReportItem, name), field_type)

    def test_job_configuration(self):
        field = model_field(BulkReportItem, "job")
        assert field.remote_field.on_delete is models.CASCADE
        assert field.remote_field.related_name == "items"

    def test_content_type_configuration(self):
        field = model_field(BulkReportItem, "target_content_type")
        assert field.remote_field.on_delete is models.PROTECT
        assert field.remote_field.related_name == "+"

    def test_generic_foreign_key_configuration(self):
        generic = next(
            f for f in BulkReportItem._meta.private_fields
            if isinstance(f, GenericForeignKey)
        )
        assert generic.name == "target_object"
        assert generic.ct_field == "target_content_type"
        assert generic.fk_field == "target_object_id"

    def test_status_configuration(self):
        field = model_field(BulkReportItem, "status")
        assert field.max_length == 20
        assert list(field.choices) == list(BulkItemStatus.choices)
        assert field.default == BulkItemStatus.PENDING
        assert field.db_index is True

    def test_generated_report_configuration(self):
        field = model_field(BulkReportItem, "generated_report")
        assert field.null is True and field.blank is True
        assert field.remote_field.on_delete is models.SET_NULL
        assert field.remote_field.related_name == "bulk_items"

    def test_error_message_configuration(self):
        field = model_field(BulkReportItem, "error_message")
        assert field.default == ""
        assert field.blank is True

    def test_ordering(self):
        assert BulkReportItem._meta.ordering == ["id"]

    @pytest.mark.parametrize(
        ("name", "fields"),
        [
            ("bulk_item_status_idx", ["job", "status"]),
            ("bulk_item_target_idx", ["target_content_type", "target_object_id"]),
        ],
    )
    def test_index_definition(self, name, fields):
        index = next(i for i in BulkReportItem._meta.indexes if i.name == name)
        assert index.fields == fields

    @pytest.mark.parametrize(
        ("status", "label"),
        [
            (BulkItemStatus.PENDING, "Pending"),
            (BulkItemStatus.SUCCESS, "Success"),
            (BulkItemStatus.FAILED, "Failed"),
        ],
    )
    def test_string(self, status, label):
        assert str(make_item(job_id=451, status=status)) == f"451 : {label}"


class TestBulkExportArchive:
    def test_inheritance(self):
        assert issubclass(BulkExportArchive, AbstractGeneratedArtifact)
        assert issubclass(BulkExportArchive, SchoolScopedModel)
        assert isinstance(BulkExportArchive.objects, SchoolScopedManager)

    @pytest.mark.parametrize(
        ("name", "field_type"),
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
            ("job", models.OneToOneField),
            ("manifest", models.JSONField),
            ("expires_at", models.DateTimeField),
            ("downloaded_count", models.PositiveIntegerField),
        ],
    )
    def test_field_types(self, name, field_type):
        assert isinstance(model_field(BulkExportArchive, name), field_type)

    def test_job_configuration(self):
        field = model_field(BulkExportArchive, "job")
        assert field.remote_field.on_delete is models.CASCADE
        assert field.remote_field.related_name == "archive"

    def test_manifest_configuration(self):
        field = model_field(BulkExportArchive, "manifest")
        assert field.default is dict
        assert field.blank is True

    def test_manifest_defaults_are_independent(self):
        first, second = BulkExportArchive(), BulkExportArchive()
        first.manifest["file.pdf"] = {"id": 1}
        assert second.manifest == {}

    def test_expires_at_configuration(self):
        field = model_field(BulkExportArchive, "expires_at")
        assert field.null is True and field.blank is True
        assert field.db_index is True

    def test_downloaded_count_default(self):
        assert model_field(BulkExportArchive, "downloaded_count").default == 0

    def test_inherited_file_upload_path(self):
        # Documents the code exactly as written. _archive_upload_path exists,
        # but the inherited file field currently uses _generated_file_upload_path.
        assert model_field(BulkExportArchive, "file").upload_to is _generated_file_upload_path

    def test_inherited_artifact_defaults(self):
        obj = BulkExportArchive()
        assert obj.file_hash == ""
        assert obj.file_size is None
        assert obj.mime_type == ""
        assert obj.export_format == ""
        assert obj.created_at is None
        assert obj.status == GeneratedReportStatus.PENDING
        assert obj.failure_message == ""

    def test_export_format_choices(self):
        field = model_field(BulkExportArchive, "export_format")
        assert list(field.choices) == list(ExportFormat.choices)

    def test_status_choices(self):
        field = model_field(BulkExportArchive, "status")
        assert list(field.choices) == list(GeneratedReportStatus.choices)

    def test_ordering(self):
        assert BulkExportArchive._meta.ordering == ["-created_at", "-pk"]

    def test_download_constraint(self):
        constraint = BulkExportArchive._meta.constraints[0]
        assert constraint.name == "bulk_archive_downloads_positive"
        assert constraint.condition == Q(downloaded_count__gte=0)

    def test_expiry_index(self):
        index = BulkExportArchive._meta.indexes[0]
        assert index.name == "bulk_archive_expiry_idx"
        assert index.fields == ["school", "expires_at"]

    @pytest.mark.parametrize("count", [0, 1, 2, 100, 999999])
    def test_clean_accepts_non_negative_count(self, count):
        make_archive(downloaded_count=count).clean()

    @pytest.mark.parametrize("count", [-1, -2, -100])
    def test_clean_rejects_negative_count(self, count):
        with pytest.raises(ValidationError) as exc_info:
            make_archive(downloaded_count=count).clean()
        assert (
    exc_info.value.message_dict["downloaded_count"][0]
    == "Download count cannot be negative."
)

    def test_string(self):
        assert str(make_archive(job_id=812)) == "Archive for Job #812"