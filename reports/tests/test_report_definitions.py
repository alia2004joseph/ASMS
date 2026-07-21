import pytest
from django.apps import apps
from django.core.exceptions import ValidationError

from reports.constants import (
    DocumentType,
    GradingDisplayFormat,
    ReportCategory,
    TemplateEngine,
)
from reports.models import ReportTemplate, ReportType

def first_choice_value(choice_class):
    """Return the stored value of the first available TextChoices option."""
    return choice_class.choices[0][0]


def make_unsaved_school(name="Test School"):
    """
    Build a valid School model instance without writing it to the database.

    These tests mainly exercise ReportTemplate model validation, so a saved
    school is unnecessary unless a database constraint is being tested.
    """
    school_model = apps.get_model("schools", "School")
    school = school_model()
    school.name = name
    return school


class TestReportType:
    def test_default_values(self):
        report_type = ReportType(
            code="student-report-card",
            name="Student Report Card",
            category=first_choice_value(ReportCategory),
        )

        assert report_type.description == ""
        assert report_type.is_active is True

    def test_string_representation_returns_name(self):
        report_type = ReportType(
            code="student-report-card",
            name="Student Report Card",
            category=first_choice_value(ReportCategory),
        )

        assert str(report_type) == "Student Report Card"

    def test_code_field_is_unique(self):
        field = ReportType._meta.get_field("code")

        assert field.unique is True

    def test_code_field_has_expected_max_length(self):
        field = ReportType._meta.get_field("code")

        assert field.max_length == 64

    def test_category_field_uses_report_category_choices(self):
        field = ReportType._meta.get_field("category")

        assert list(field.choices) == list(ReportCategory.choices)

    def test_default_ordering(self):
        assert ReportType._meta.ordering == ["category", "name"]

    def test_category_and_active_index_exists(self):
        index_names = {
            index.name for index in ReportType._meta.indexes
        }

        assert "reporttype_category_active_idx" in index_names


class TestReportTemplateDefaults:
    def test_default_values(self):
        template = ReportTemplate(
            school_id=1,
            document_type=first_choice_value(DocumentType),
        )

        assert template.template_engine == TemplateEngine.HTML
        assert template.branding == {}
        assert template.page_config == {}
        assert template.placement_config == {}
        assert template.layout_config == {}
        assert (
            template.grading_display_format
            == GradingDisplayFormat.LETTER
        )
        assert template.version == 1
        assert template.is_active is True
        assert template.is_default is False
        assert template.is_system_default is False
        assert template.report_type is None
        assert not template.preview_image

    def test_json_defaults_are_not_shared_between_instances(self):
        first = ReportTemplate(
            school_id=1,
            document_type=first_choice_value(DocumentType),
        )
        second = ReportTemplate(
            school_id=2,
            document_type=first_choice_value(DocumentType),
        )

        first.branding["logo"] = "logo.png"
        first.page_config["orientation"] = "landscape"
        first.placement_config["stamp"] = "bottom-right"
        first.layout_config["columns"] = 2

        assert second.branding == {}
        assert second.page_config == {}
        assert second.placement_config == {}
        assert second.layout_config == {}

    def test_template_engine_uses_expected_choices(self):
        field = ReportTemplate._meta.get_field("template_engine")

        assert list(field.choices) == list(TemplateEngine.choices)

    def test_document_type_uses_expected_choices(self):
        field = ReportTemplate._meta.get_field("document_type")

        assert list(field.choices) == list(DocumentType.choices)

    def test_grading_display_uses_expected_choices(self):
        field = ReportTemplate._meta.get_field(
            "grading_display_format"
        )

        assert list(field.choices) == list(
            GradingDisplayFormat.choices
        )

    def test_report_type_is_optional(self):
        field = ReportTemplate._meta.get_field("report_type")

        assert field.null is True
        assert field.blank is True

    def test_school_is_optional_at_database_field_level(self):
        field = ReportTemplate._meta.get_field("school")

        assert field.null is True
        assert field.blank is True

    def test_template_default_ordering(self):
        assert ReportTemplate._meta.ordering == [
            "document_type",
            "-is_default",
            "-is_active",
            "-version",
        ]


class TestReportTemplateValidation:
    def test_school_template_passes_validation(self):
        template = ReportTemplate(
            school_id=10,
            document_type=first_choice_value(DocumentType),
            is_system_default=False,
        )

        assert template.clean() is None

    def test_system_default_without_school_passes_validation(self):
        template = ReportTemplate(
            school=None,
            document_type=first_choice_value(DocumentType),
            is_system_default=True,
        )

        assert template.clean() is None

    def test_template_without_school_must_be_system_default(self):
        template = ReportTemplate(
            school=None,
            document_type=first_choice_value(DocumentType),
            is_system_default=False,
        )

        with pytest.raises(ValidationError) as exc_info:
            template.clean()

        assert "school" in exc_info.value.message_dict

    def test_system_default_cannot_have_school(self):
        template = ReportTemplate(
            school_id=7,
            document_type=first_choice_value(DocumentType),
            is_system_default=True,
        )

        with pytest.raises(ValidationError) as exc_info:
            template.clean()

        assert "is_system_default" in exc_info.value.message_dict

    def test_inactive_template_cannot_be_default(self):
        template = ReportTemplate(
            school_id=7,
            document_type=first_choice_value(DocumentType),
            is_active=False,
            is_default=True,
        )

        with pytest.raises(ValidationError) as exc_info:
            template.clean()

        assert "is_default" in exc_info.value.message_dict

    def test_version_must_be_at_least_one(self):
        template = ReportTemplate(
            school_id=7,
            document_type=first_choice_value(DocumentType),
            version=0,
        )

        with pytest.raises(ValidationError) as exc_info:
            template.clean()

        assert "version" in exc_info.value.message_dict

    def test_validation_collects_multiple_errors(self):
        template = ReportTemplate(
            school=None,
            document_type=first_choice_value(DocumentType),
            is_system_default=False,
            is_default=True,
            is_active=False,
            version=0,
        )

        with pytest.raises(ValidationError) as exc_info:
            template.clean()

        errors = exc_info.value.message_dict

        assert "school" in errors
        assert "is_default" in errors
        assert "version" in errors

    def test_active_default_school_template_is_valid(self):
        template = ReportTemplate(
            school_id=25,
            document_type=first_choice_value(DocumentType),
            is_system_default=False,
            is_active=True,
            is_default=True,
            version=1,
        )

        assert template.clean() is None

    def test_active_system_default_template_is_valid(self):
        template = ReportTemplate(
            school=None,
            document_type=first_choice_value(DocumentType),
            is_system_default=True,
            is_active=True,
            is_default=True,
            version=1,
        )

        assert template.clean() is None


class TestReportTemplateStringRepresentation:
    def test_system_template_string_contains_system_owner(self):
        template = ReportTemplate(
            school=None,
            document_type=first_choice_value(DocumentType),
            is_system_default=True,
            version=3,
        )

        expected = (
            f"SYSTEM - {template.get_document_type_display()} (v3)"
        )

        assert str(template) == expected

    def test_school_template_string_contains_school_name(self):
        school = make_unsaved_school("Makerere Demonstration School")

        template = ReportTemplate(
            school=school,
            document_type=first_choice_value(DocumentType),
            is_system_default=False,
            version=2,
        )

        expected = (
            "Makerere Demonstration School - "
            f"{template.get_document_type_display()} (v2)"
        )

        assert str(template) == expected


class TestReportTemplateConstraints:
    def test_expected_constraint_names_exist(self):
        constraint_names = {
            constraint.name
            for constraint in ReportTemplate._meta.constraints
        }

        assert constraint_names == {
            "reporttemplate_school_or_system_default",
            "reporttemplate_system_default_has_no_school",
            "unique_school_document_template_version",
            "unique_system_document_template_version",
            "unique_active_school_default_template",
            "unique_active_system_default_template",
        }

    def test_expected_index_names_exist(self):
        index_names = {
            index.name for index in ReportTemplate._meta.indexes
        }

        assert index_names == {
            "rpttpl_school_doc_idx",
            "rpttpl_fallback_idx",
            "reporttemplate_type_active_idx",
        }