from django.db import models

from reports.constants import (
    ExportFormat,
    GeneratedReportStatus,
    ReportScope,
)
from reports.models import (
    GeneratedReport,
    ReportExportLog,
    ReportType,
)


def first_choice_value(choice_class):
    """Return the stored value of the first available choice."""
    return choice_class.choices[0][0]


def make_report_type(
    name="Student Report Card",
    code="student-report-card",
):
    return ReportType(
        name=name,
        code=code,
        category="ACADEMIC",
    )


def make_generated_report(
    *,
    report_type=None,
    school_id=1,
    scope=None,
    **kwargs,
):
    return GeneratedReport(
        report_type=report_type or make_report_type(),
        school_id=school_id,
        scope=scope or first_choice_value(ReportScope),
        **kwargs,
    )


class TestGeneratedReportDefaults:
    def test_default_values(self):
        report = make_generated_report()

        assert report.parameters == {}
        assert report.requested_by is None
        assert report.requested_by_id is None

        assert report.version == 1
        assert report.previous_version is None
        assert report.is_latest is True
        assert report.regeneration_reason == ""

        assert report.is_revoked is False
        assert report.revoked_reason == ""
        assert report.revoked_at is None
        assert report.revoked_by is None

        assert report.file_hash == ""
        assert report.file_size is None
        assert report.mime_type == ""
        assert report.export_format == ""
        assert report.status == GeneratedReportStatus.PENDING
        assert report.failure_message == ""

    def test_parameters_default_is_not_shared(self):
        first = make_generated_report()
        second = make_generated_report()

        first.parameters["student_id"] = 25

        assert second.parameters == {}

    def test_root_ids_are_unique_for_new_reports(self):
        first = make_generated_report()
        second = make_generated_report()

        assert first.root_id != second.root_id

    def test_scope_uses_report_scope_choices(self):
        field = GeneratedReport._meta.get_field("scope")

        assert list(field.choices) == list(ReportScope.choices)

    def test_report_type_is_required(self):
        field = GeneratedReport._meta.get_field("report_type")

        assert field.null is False
        assert field.blank is False

    def test_requested_by_is_optional(self):
        field = GeneratedReport._meta.get_field("requested_by")

        assert field.null is True
        assert field.blank is True

    def test_report_type_uses_protect_on_delete(self):
        field = GeneratedReport._meta.get_field("report_type")

        assert field.remote_field.on_delete is models.PROTECT

    def test_requested_by_uses_set_null_on_delete(self):
        field = GeneratedReport._meta.get_field("requested_by")

        assert field.remote_field.on_delete is models.SET_NULL

    def test_generated_report_has_school_scoped_manager(self):
        assert hasattr(GeneratedReport.objects, "for_school")


class TestGeneratedReportMetadata:
    def test_default_ordering(self):
        assert GeneratedReport._meta.ordering == [
            "-created_at",
            "-pk",
        ]

    def test_expected_constraint_names_exist(self):
        constraint_names = {
            constraint.name
            for constraint in GeneratedReport._meta.constraints
        }

        assert constraint_names == {
            "generated_report_version_gte_1",
            "unique_generated_report_chain_version",
            "unique_latest_generated_report",
        }

    def test_expected_index_names_exist(self):
        index_names = {
            index.name
            for index in GeneratedReport._meta.indexes
        }

        assert index_names == {
            "gen_school_type_idx",
            "gen_report_school_status_idx",
            "gen_req_created_idx",
            "gen_report_root_version_idx",
            "gen_report_latest_type_idx",
            "gen_report_school_scope_idx",
        }

    def test_version_field_is_positive_integer(self):
        field = GeneratedReport._meta.get_field("version")

        assert isinstance(field, models.PositiveIntegerField)

    def test_parameters_is_json_field(self):
        field = GeneratedReport._meta.get_field("parameters")

        assert isinstance(field, models.JSONField)

    def test_status_uses_generated_report_status_choices(self):
        field = GeneratedReport._meta.get_field("status")

        assert list(field.choices) == list(
            GeneratedReportStatus.choices
        )


class TestGeneratedReportStringRepresentation:
    def test_string_contains_report_name_version_and_status(self):
        report_type = make_report_type(name="Academic Transcript")

        report = make_generated_report(
            report_type=report_type,
            version=3,
            status=GeneratedReportStatus.PENDING,
        )

        expected = (
            "Academic Transcript "
            f"(v3) - {report.get_status_display()}"
        )

        assert str(report) == expected

    def test_failed_report_string_uses_status_display(self):
        report = make_generated_report(
            version=2,
            status=GeneratedReportStatus.FAILED,
        )

        assert str(report) == (
            "Student Report Card "
            f"(v2) - {report.get_status_display()}"
        )


class TestReportExportLogDefaults:
    def test_default_values(self):
        generated_report = make_generated_report()

        export_log = ReportExportLog(
            generated_report=generated_report,
            export_format=first_choice_value(ExportFormat),
        )

        assert export_log.downloaded_by is None
        assert export_log.downloaded_by_id is None
        assert export_log.ip_address is None
        assert export_log.user_agent == ""
        assert export_log.successful is True
        assert export_log.failure_message == ""

    def test_export_format_uses_expected_choices(self):
        field = ReportExportLog._meta.get_field("export_format")

        assert list(field.choices) == list(ExportFormat.choices)

    def test_generated_report_is_required(self):
        field = ReportExportLog._meta.get_field(
            "generated_report"
        )

        assert field.null is False
        assert field.blank is False

    def test_generated_report_uses_protect_on_delete(self):
        field = ReportExportLog._meta.get_field(
            "generated_report"
        )

        assert field.remote_field.on_delete is models.PROTECT

    def test_downloaded_by_is_optional(self):
        field = ReportExportLog._meta.get_field("downloaded_by")

        assert field.null is True
        assert field.blank is True

    def test_downloaded_by_uses_set_null(self):
        field = ReportExportLog._meta.get_field("downloaded_by")

        assert field.remote_field.on_delete is models.SET_NULL

    def test_downloaded_at_uses_auto_now_add(self):
        field = ReportExportLog._meta.get_field("downloaded_at")

        assert field.auto_now_add is True
        assert field.db_index is True

    def test_ip_address_is_optional(self):
        field = ReportExportLog._meta.get_field("ip_address")

        assert field.null is True
        assert field.blank is True

    def test_user_agent_max_length(self):
        field = ReportExportLog._meta.get_field("user_agent")

        assert field.max_length == 512


class TestReportExportLogMetadata:
    def test_default_ordering(self):
        assert ReportExportLog._meta.ordering == [
            "-downloaded_at",
        ]

    def test_expected_index_names_exist(self):
        index_names = {
            index.name
            for index in ReportExportLog._meta.indexes
        }

        assert index_names == {
            "report_export_report_time_idx",
            "report_export_user_time_idx",
            "report_export_success_time_idx",
        }


class TestReportExportLogStringRepresentation:
    def test_anonymous_successful_download_string(self):
        report = make_generated_report(
            report_type=make_report_type(
                name="Examination Permit",
                code="examination-permit",
            )
        )

        export_log = ReportExportLog(
            generated_report=report,
            export_format=first_choice_value(ExportFormat),
            successful=True,
        )

        assert str(export_log) == (
            "Examination Permit download by "
            "Anonymous/Deleted User (successful)"
        )

    def test_anonymous_failed_download_string(self):
        report = make_generated_report(
            report_type=make_report_type(
                name="Fee Clearance Certificate",
                code="fee-clearance-certificate",
            )
        )

        export_log = ReportExportLog(
            generated_report=report,
            export_format=first_choice_value(ExportFormat),
            successful=False,
            failure_message="File is unavailable.",
        )

        assert str(export_log) == (
            "Fee Clearance Certificate download by "
            "Anonymous/Deleted User (failed)"
        )