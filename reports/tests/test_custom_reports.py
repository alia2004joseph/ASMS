import pytest
from django.core.exceptions import ValidationError
from django.db import models

from reports.constants import (
    AggregateFunction,
    FieldDataType,
    FilterOperator,
    GeneratedReportStatus,
    SortDirection,
)
from reports.models import (
    CustomReportDefinition,
    CustomReportExecution,
    CustomReportField,
    CustomReportFilter,
    CustomReportGroup,
    CustomReportSort,
)


def first_choice_value(choice_class):
    """Return the stored value of the first available TextChoices option."""
    return choice_class.choices[0][0]


def make_definition(
    *,
    name="Student Performance Report",
    school_id=1,
    owner_id=1,
    data_source_key="student_results",
    **kwargs,
):
    return CustomReportDefinition(
        school_id=school_id,
        owner_id=owner_id,
        name=name,
        data_source_key=data_source_key,
        **kwargs,
    )


class TestCustomReportDefinitionDefaults:
    def test_default_values(self):
        definition = make_definition()

        assert definition.description == ""
        assert definition.is_public is False
        assert definition.is_active is True

    def test_string_representation_returns_name(self):
        definition = make_definition(name="Attendance Summary")

        assert str(definition) == "Attendance Summary"

    def test_owner_is_required(self):
        field = CustomReportDefinition._meta.get_field("owner")

        assert field.null is False
        assert field.blank is False

    def test_owner_uses_cascade_on_delete(self):
        field = CustomReportDefinition._meta.get_field("owner")

        assert field.remote_field.on_delete is models.CASCADE

    def test_school_scoped_manager_is_available(self):
        assert hasattr(CustomReportDefinition.objects, "for_school")

    def test_data_source_key_has_expected_max_length(self):
        field = CustomReportDefinition._meta.get_field(
            "data_source_key"
        )

        assert field.max_length == 100
        assert field.db_index is True

    def test_name_has_expected_max_length(self):
        field = CustomReportDefinition._meta.get_field("name")

        assert field.max_length == 150

    def test_default_ordering(self):
        assert CustomReportDefinition._meta.ordering == ["name"]

    def test_expected_constraint_names_exist(self):
        constraint_names = {
            constraint.name
            for constraint in CustomReportDefinition._meta.constraints
        }

        assert constraint_names == {
            "unique_custom_report_name_per_owner",
        }

    def test_expected_index_names_exist(self):
        index_names = {
            index.name
            for index in CustomReportDefinition._meta.indexes
        }

        assert index_names == {
            "custom_report_owner_idx",
            "custom_report_public_idx",
            "custom_report_source_idx",
        }


class TestCustomReportFieldDefaults:
    def test_default_values(self):
        field = CustomReportField(
            definition=make_definition(),
            field_key="student_name",
            display_label="Student Name",
        )

        assert field.data_type == FieldDataType.STRING
        assert field.order == 0
        assert field.is_aggregate is False
        assert field.aggregate_function is None

    def test_string_representation_returns_display_label(self):
        field = CustomReportField(
            definition=make_definition(),
            field_key="student_name",
            display_label="Student Name",
        )

        assert str(field) == "Student Name"

    def test_definition_uses_cascade_on_delete(self):
        field = CustomReportField._meta.get_field("definition")

        assert field.remote_field.on_delete is models.CASCADE

    def test_field_key_has_expected_max_length(self):
        field = CustomReportField._meta.get_field("field_key")

        assert field.max_length == 150

    def test_display_label_has_expected_max_length(self):
        field = CustomReportField._meta.get_field("display_label")

        assert field.max_length == 150

    def test_data_type_uses_expected_choices(self):
        field = CustomReportField._meta.get_field("data_type")

        assert list(field.choices) == list(FieldDataType.choices)

    def test_aggregate_function_uses_expected_choices(self):
        field = CustomReportField._meta.get_field(
            "aggregate_function"
        )

        assert list(field.choices) == list(
            AggregateFunction.choices
        )
        assert field.null is True
        assert field.blank is True

    def test_default_ordering(self):
        assert CustomReportField._meta.ordering == ["order"]

    def test_expected_constraint_exists(self):
        constraint_names = {
            constraint.name
            for constraint in CustomReportField._meta.constraints
        }

        assert constraint_names == {
            "unique_custom_report_field",
        }


class TestCustomReportFieldValidation:
    def test_non_aggregate_without_function_is_valid(self):
        field = CustomReportField(
            definition=make_definition(),
            field_key="student_name",
            display_label="Student Name",
            is_aggregate=False,
            aggregate_function=None,
        )

        assert field.clean() is None

    def test_aggregate_with_function_is_valid(self):
        field = CustomReportField(
            definition=make_definition(),
            field_key="average_mark",
            display_label="Average Mark",
            is_aggregate=True,
            aggregate_function=first_choice_value(
                AggregateFunction
            ),
        )

        assert field.clean() is None

    def test_aggregate_requires_function(self):
        field = CustomReportField(
            definition=make_definition(),
            field_key="average_mark",
            display_label="Average Mark",
            is_aggregate=True,
            aggregate_function=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            field.clean()

        assert "aggregate_function" in (
            exc_info.value.message_dict
        )

    def test_non_aggregate_cannot_define_function(self):
        field = CustomReportField(
            definition=make_definition(),
            field_key="student_name",
            display_label="Student Name",
            is_aggregate=False,
            aggregate_function=first_choice_value(
                AggregateFunction
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            field.clean()

        assert "aggregate_function" in (
            exc_info.value.message_dict
        )


class TestCustomReportFilter:
    def test_default_values(self):
        report_filter = CustomReportFilter(
            definition=make_definition(),
            field_key="classroom",
            operator=first_choice_value(FilterOperator),
            value="Senior One",
        )

        assert report_filter.is_date_range is False

    def test_string_representation(self):
        operator = first_choice_value(FilterOperator)

        report_filter = CustomReportFilter(
            definition=make_definition(),
            field_key="classroom",
            operator=operator,
            value="Senior One",
        )

        assert str(report_filter) == f"classroom ({operator})"

    def test_definition_uses_cascade_on_delete(self):
        field = CustomReportFilter._meta.get_field("definition")

        assert field.remote_field.on_delete is models.CASCADE

    def test_operator_uses_expected_choices(self):
        field = CustomReportFilter._meta.get_field("operator")

        assert list(field.choices) == list(FilterOperator.choices)

    def test_value_is_json_field(self):
        field = CustomReportFilter._meta.get_field("value")

        assert isinstance(field, models.JSONField)

    def test_expected_index_exists(self):
        index_names = {
            index.name
            for index in CustomReportFilter._meta.indexes
        }

        assert index_names == {
            "custom_filter_field_idx",
        }


class TestCustomReportSort:
    def test_default_values(self):
        report_sort = CustomReportSort(
            definition=make_definition(),
            field_key="student_name",
        )

        assert report_sort.direction == SortDirection.ASC
        assert report_sort.order == 0

    def test_string_representation(self):
        report_sort = CustomReportSort(
            definition=make_definition(),
            field_key="student_name",
            direction=SortDirection.ASC,
        )

        assert str(report_sort) == (
            f"student_name ({SortDirection.ASC})"
        )

    def test_direction_uses_expected_choices(self):
        field = CustomReportSort._meta.get_field("direction")

        assert list(field.choices) == list(SortDirection.choices)

    def test_definition_uses_cascade_on_delete(self):
        field = CustomReportSort._meta.get_field("definition")

        assert field.remote_field.on_delete is models.CASCADE

    def test_default_ordering(self):
        assert CustomReportSort._meta.ordering == ["order"]

    def test_expected_constraint_exists(self):
        constraint_names = {
            constraint.name
            for constraint in CustomReportSort._meta.constraints
        }

        assert constraint_names == {
            "unique_sort_order",
        }


class TestCustomReportGroup:
    def test_default_values(self):
        group = CustomReportGroup(
            definition=make_definition(),
            field_key="classroom",
        )

        assert group.order == 0
        assert group.show_subtotal is False
        assert group.show_grand_total is False

    def test_string_representation_returns_field_key(self):
        group = CustomReportGroup(
            definition=make_definition(),
            field_key="classroom",
        )

        assert str(group) == "classroom"

    def test_definition_uses_cascade_on_delete(self):
        field = CustomReportGroup._meta.get_field("definition")

        assert field.remote_field.on_delete is models.CASCADE

    def test_default_ordering(self):
        assert CustomReportGroup._meta.ordering == ["order"]

    def test_expected_constraint_exists(self):
        constraint_names = {
            constraint.name
            for constraint in CustomReportGroup._meta.constraints
        }

        assert constraint_names == {
            "unique_group_order",
        }


class TestCustomReportExecutionDefaults:
    def test_default_values(self):
        execution = CustomReportExecution(
            school_id=1,
            definition=make_definition(),
        )

        assert execution.executed_by is None
        assert execution.executed_by_id is None
        assert execution.parameters_snapshot == {}
        assert execution.row_count == 0
        assert execution.generated_report is None
        assert execution.generated_report_id is None
        assert execution.status == GeneratedReportStatus.PENDING

    def test_parameters_snapshot_default_is_not_shared(self):
        first = CustomReportExecution(
            school_id=1,
            definition=make_definition(),
        )
        second = CustomReportExecution(
            school_id=1,
            definition=make_definition(),
        )

        first.parameters_snapshot["classroom_id"] = 10

        assert second.parameters_snapshot == {}

    def test_definition_uses_cascade_on_delete(self):
        field = CustomReportExecution._meta.get_field(
            "definition"
        )

        assert field.remote_field.on_delete is models.CASCADE

    def test_executed_by_is_optional(self):
        field = CustomReportExecution._meta.get_field(
            "executed_by"
        )

        assert field.null is True
        assert field.blank is True

    def test_executed_by_uses_set_null(self):
        field = CustomReportExecution._meta.get_field(
            "executed_by"
        )

        assert field.remote_field.on_delete is models.SET_NULL

    def test_generated_report_is_optional(self):
        field = CustomReportExecution._meta.get_field(
            "generated_report"
        )

        assert field.null is True
        assert field.blank is True

    def test_generated_report_uses_set_null(self):
        field = CustomReportExecution._meta.get_field(
            "generated_report"
        )

        assert field.remote_field.on_delete is models.SET_NULL

    def test_status_uses_expected_choices(self):
        field = CustomReportExecution._meta.get_field("status")

        assert list(field.choices) == list(
            GeneratedReportStatus.choices
        )
        assert field.db_index is True

    def test_executed_at_uses_auto_now_add(self):
        field = CustomReportExecution._meta.get_field(
            "executed_at"
        )

        assert field.auto_now_add is True
        assert field.db_index is True

    def test_school_scoped_manager_is_available(self):
        assert hasattr(CustomReportExecution.objects, "for_school")


class TestCustomReportExecutionMetadata:
    def test_default_ordering(self):
        assert CustomReportExecution._meta.ordering == [
            "-executed_at"
        ]

    def test_expected_index_names_exist(self):
        index_names = {
            index.name
            for index in CustomReportExecution._meta.indexes
        }

        assert index_names == {
            "custom_exec_definition_idx",
            "custom_exec_status_idx",
        }


class TestCustomReportExecutionStringRepresentation:
    def test_string_contains_definition_and_status(self):
        definition = make_definition(
            name="Class Performance Report"
        )

        execution = CustomReportExecution(
            school_id=1,
            definition=definition,
            status=GeneratedReportStatus.PENDING,
        )

        assert str(execution) == (
            "Class Performance Report "
            f"({execution.get_status_display()})"
        )

    def test_failed_execution_uses_status_display(self):
        definition = make_definition(
            name="Attendance Report"
        )

        execution = CustomReportExecution(
            school_id=1,
            definition=definition,
            status=GeneratedReportStatus.FAILED,
        )

        assert str(execution) == (
            "Attendance Report "
            f"({execution.get_status_display()})"
        )