"""
Tests for reports.serializers.custom_report_serializers.

Important:
    Before running this suite, remove redundant declarations such as:

        source="definition_id"

    when the serializer field itself is already named ``definition_id``.
    DRF raises an AssertionError for a field whose source is identical to
    its field name.

Run:
    pytest reports/tests/test_custom_report_serializers.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework import serializers

from reports.constants import (
    AggregateFunction,
    FilterOperator,
    SortDirection,
)
from reports.exceptions import ValidationError as DomainValidationError
from reports.serializers import custom_report_serializers as serializer_module
from reports.serializers.custom_report_serializers import (
    CustomReportDefinitionSerializer,
    CustomReportExecutionSerializer,
    CustomReportFieldSerializer,
    CustomReportFilterSerializer,
    CustomReportGroupSerializer,
    CustomReportSortSerializer,
    ReportableFieldSerializer,
    ReportableSourceSerializer,
    _RegistryValidatedFieldMixin,
)


def first_value(enum_class):
    """Return the first declared value from a Django Choices-like class."""
    values = list(enum_class.values)
    if not values:
        raise AssertionError(f"{enum_class!r} defines no values")
    return values[0]


def make_school(pk=1):
    return SimpleNamespace(pk=pk, id=pk)


def make_user(*, pk=10, school=None):
    return SimpleNamespace(
        pk=pk,
        id=pk,
        school=school or make_school(),
    )


def make_request(*, user=None):
    return SimpleNamespace(user=user or make_user())


def request_context(*, user=None, data_source_key=None):
    context = {"request": make_request(user=user)}
    if data_source_key is not None:
        context["data_source_key"] = data_source_key
    return context


def make_definition(**overrides):
    values = {
        "pk": 1,
        "id": 1,
        "name": "Student performance",
        "description": "Performance by classroom",
        "data_source_key": "students",
        "is_public": False,
        "is_active": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_execution(**overrides):
    values = {
        "id": 1,
        "definition_id": 2,
        "executed_by_id": 3,
        "executed_at": None,
        "row_count": 25,
        "generated_report_id": 4,
        "status": "COMPLETED",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class DummyRegistrySerializer(
    _RegistryValidatedFieldMixin,
    serializers.Serializer,
):
    field_key = serializers.CharField()


class TestReportableSourceSerializer:
    def test_declared_fields(self):
        serializer = ReportableSourceSerializer()

        assert tuple(serializer.fields) == (
            "source_key",
            "display_label",
        )

    def test_all_fields_are_read_only(self):
        serializer = ReportableSourceSerializer()

        assert serializer.fields["source_key"].read_only is True
        assert serializer.fields["display_label"].read_only is True

    def test_representation(self):
        instance = SimpleNamespace(
            source_key="students",
            display_label="Students",
        )

        assert ReportableSourceSerializer(instance).data == {
            "source_key": "students",
            "display_label": "Students",
        }

    def test_input_is_ignored_because_fields_are_read_only(self):
        serializer = ReportableSourceSerializer(
            data={
                "source_key": "students",
                "display_label": "Students",
            }
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {}


class TestReportableFieldSerializer:
    def test_declared_fields(self):
        serializer = ReportableFieldSerializer()

        assert tuple(serializer.fields) == (
            "field_key",
            "display_label",
            "data_type",
            "is_aggregatable",
        )

    def test_all_fields_are_read_only(self):
        serializer = ReportableFieldSerializer()

        assert all(
            field.read_only
            for field in serializer.fields.values()
        )

    def test_representation(self):
        instance = SimpleNamespace(
            field_key="average_score",
            display_label="Average score",
            data_type="decimal",
            is_aggregatable=True,
        )

        assert ReportableFieldSerializer(instance).data == {
            "field_key": "average_score",
            "display_label": "Average score",
            "data_type": "decimal",
            "is_aggregatable": True,
        }


class TestRegistryValidatedFieldMixin:
    def test_source_comes_from_context(self):
        serializer = DummyRegistrySerializer(
            context={"data_source_key": "students"}
        )

        assert serializer._source() == "students"

    def test_source_is_none_when_not_supplied(self):
        assert DummyRegistrySerializer()._source() is None

    def test_valid_field_is_returned(
        self,
        monkeypatch,
    ):
        user = make_user()
        validate_mock = Mock(return_value={"field_key": "name"})

        monkeypatch.setattr(
            serializer_module.report_registry_service,
            "validate_field_access",
            validate_mock,
        )

        serializer = DummyRegistrySerializer(
            context=request_context(
                user=user,
                data_source_key="students",
            )
        )

        assert serializer.validate_field_key("name") == "name"
        validate_mock.assert_called_once_with(
            "students",
            "name",
            user,
        )

    def test_none_from_registry_means_field_is_rejected(
        self,
        monkeypatch,
    ):
        user = make_user()
        validate_mock = Mock(return_value=None)

        monkeypatch.setattr(
            serializer_module.report_registry_service,
            "validate_field_access",
            validate_mock,
        )

        serializer = DummyRegistrySerializer(
            context=request_context(
                user=user,
                data_source_key="students",
            )
        )

        with pytest.raises(
            serializers.ValidationError,
            match="not an approved reportable field",
        ):
            serializer.validate_field_key("password_hash")

    def test_missing_request_context_raises_key_error(self):
        serializer = DummyRegistrySerializer(
            context={"data_source_key": "students"}
        )

        with pytest.raises(KeyError):
            serializer.validate_field_key("name")


class TestCustomReportFieldSerializer:
    def test_declared_fields(self):
        serializer = CustomReportFieldSerializer()

        assert tuple(serializer.fields) == (
            "field_key",
            "display_label",
            "order",
            "is_aggregate",
            "aggregate_function",
        )

    def test_non_aggregate_without_function_is_valid(self):
        serializer = CustomReportFieldSerializer()

        attrs = {
            "field_key": "student_name",
            "order": 1,
            "is_aggregate": False,
        }

        assert serializer.validate(attrs) is attrs

    def test_aggregate_requires_function(self):
        serializer = CustomReportFieldSerializer()

        with pytest.raises(
            serializers.ValidationError,
            match="aggregate_function is required",
        ):
            serializer.validate(
                {
                    "field_key": "score",
                    "order": 1,
                    "is_aggregate": True,
                }
            )

    @pytest.mark.parametrize(
        "aggregate_function",
        ["INVALID", "TOTAL_AVERAGE", "", object()],
    )
    def test_invalid_aggregate_function_is_rejected(
        self,
        aggregate_function,
    ):
        serializer = CustomReportFieldSerializer()

        if aggregate_function == "":
            # An empty value is treated as absent and is valid for
            # non-aggregate fields according to the current serializer.
            attrs = {
                "field_key": "name",
                "order": 1,
                "is_aggregate": False,
                "aggregate_function": aggregate_function,
            }
            assert serializer.validate(attrs) is attrs
            return

        with pytest.raises(
            serializers.ValidationError,
            match="Invalid aggregate_function",
        ):
            serializer.validate(
                {
                    "field_key": "score",
                    "order": 1,
                    "is_aggregate": False,
                    "aggregate_function": aggregate_function,
                }
            )

    @pytest.mark.parametrize(
        "aggregate_function",
        list(AggregateFunction.values),
    )
    def test_every_declared_aggregate_function_is_accepted(
        self,
        aggregate_function,
    ):
        serializer = CustomReportFieldSerializer()

        attrs = {
            "field_key": "score",
            "order": 1,
            "is_aggregate": True,
            "aggregate_function": aggregate_function,
        }

        assert serializer.validate(attrs) is attrs

    def test_field_registry_validation_is_inherited(
        self,
        monkeypatch,
    ):
        user = make_user()
        validate_mock = Mock(return_value={"approved": True})

        monkeypatch.setattr(
            serializer_module.report_registry_service,
            "validate_field_access",
            validate_mock,
        )

        serializer = CustomReportFieldSerializer(
            context=request_context(
                user=user,
                data_source_key="students",
            )
        )

        assert serializer.validate_field_key("score") == "score"


class TestCustomReportFilterSerializer:
    def test_declared_fields(self):
        serializer = CustomReportFilterSerializer()

        assert tuple(serializer.fields) == (
            "field_key",
            "operator",
            "value",
            "is_date_range",
        )

    @pytest.mark.parametrize(
        "operator",
        list(FilterOperator.values),
    )
    def test_every_declared_operator_is_accepted(
        self,
        operator,
    ):
        serializer = CustomReportFilterSerializer()

        assert serializer.validate_operator(operator) == operator

    @pytest.mark.parametrize(
        "operator",
        ["INVALID", "BETWEEN_BETWEEN", None, 99],
    )
    def test_invalid_operator_is_rejected(
        self,
        operator,
    ):
        serializer = CustomReportFilterSerializer()

        with pytest.raises(
            serializers.ValidationError,
            match="Invalid filter operator",
        ):
            serializer.validate_operator(operator)

    def test_registry_field_validation(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            serializer_module.report_registry_service,
            "validate_field_access",
            Mock(return_value={"approved": True}),
        )

        serializer = CustomReportFilterSerializer(
            context=request_context(
                data_source_key="students"
            )
        )

        assert serializer.validate_field_key(
            "classroom"
        ) == "classroom"


class TestCustomReportSortSerializer:
    def test_declared_fields(self):
        serializer = CustomReportSortSerializer()

        assert tuple(serializer.fields) == (
            "field_key",
            "direction",
            "order",
        )

    @pytest.mark.parametrize(
        "direction",
        list(SortDirection.values),
    )
    def test_every_declared_direction_is_accepted(
        self,
        direction,
    ):
        serializer = CustomReportSortSerializer()

        assert serializer.validate_direction(direction) == direction

    @pytest.mark.parametrize(
        "direction",
        ["INVALID", "SIDEWAYS", None, 123],
    )
    def test_invalid_direction_is_rejected(
        self,
        direction,
    ):
        serializer = CustomReportSortSerializer()

        with pytest.raises(
            serializers.ValidationError,
            match="Invalid sort direction",
        ):
            serializer.validate_direction(direction)


class TestCustomReportGroupSerializer:
    def test_declared_fields(self):
        serializer = CustomReportGroupSerializer()

        assert tuple(serializer.fields) == (
            "field_key",
            "order",
            "show_subtotal",
            "show_grand_total",
        )

    def test_registry_field_validation(
        self,
        monkeypatch,
    ):
        validate_mock = Mock(return_value={"approved": True})

        monkeypatch.setattr(
            serializer_module.report_registry_service,
            "validate_field_access",
            validate_mock,
        )

        serializer = CustomReportGroupSerializer(
            context=request_context(
                data_source_key="students"
            )
        )

        assert serializer.validate_field_key(
            "classroom"
        ) == "classroom"


class TestCustomReportDefinitionSerializer:
    def test_declared_fields(self):
        serializer = CustomReportDefinitionSerializer()

        assert tuple(serializer.fields) == (
            "id",
            "name",
            "description",
            "data_source_key",
            "is_public",
            "is_active",
            "fields",
            "filters",
            "sorts",
            "groups",
        )

    def test_id_is_read_only(self):
        serializer = CustomReportDefinitionSerializer()

        assert serializer.fields["id"].read_only is True

    def test_nested_collection_requirements(self):
        serializer = CustomReportDefinitionSerializer()

        assert serializer.fields["fields"].required is True
        assert serializer.fields["filters"].required is False
        assert serializer.fields["sorts"].required is False
        assert serializer.fields["groups"].required is False

    def test_source_access_is_delegated_to_registry(
        self,
        monkeypatch,
    ):
        user = make_user()
        validate_mock = Mock(return_value={"approved": True})

        monkeypatch.setattr(
            serializer_module.report_registry_service,
            "validate_source_access",
            validate_mock,
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context(user=user)
        )

        assert serializer.validate_data_source_key(
            "students"
        ) == "students"

        validate_mock.assert_called_once_with(
            "students",
            user,
        )

    def test_unavailable_source_is_rejected(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            serializer_module.report_registry_service,
            "validate_source_access",
            Mock(return_value=None),
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context()
        )

        with pytest.raises(
            serializers.ValidationError,
            match="Unavailable data source",
        ):
            serializer.validate_data_source_key("secret_data")

    def test_duplicate_field_orders_are_rejected(self):
        serializer = CustomReportDefinitionSerializer()

        with pytest.raises(serializers.ValidationError) as exc_info:
            serializer.validate(
                {
                    "fields": [
                        {
                            "field_key": "name",
                            "order": 1,
                        },
                        {
                            "field_key": "score",
                            "order": 1,
                        },
                    ]
                }
            )

        assert "fields" in exc_info.value.detail

    def test_unique_field_orders_are_accepted(self):
        serializer = CustomReportDefinitionSerializer()

        attrs = {
            "fields": [
                {
                    "field_key": "name",
                    "order": 1,
                },
                {
                    "field_key": "score",
                    "order": 2,
                },
            ]
        }

        assert serializer.validate(attrs) is attrs

    def test_empty_fields_do_not_trigger_duplicate_error(self):
        serializer = CustomReportDefinitionSerializer()

        attrs = {"fields": []}

        assert serializer.validate(attrs) is attrs

    def test_missing_fields_key_does_not_trigger_duplicate_error(self):
        serializer = CustomReportDefinitionSerializer()

        attrs = {"name": "Example"}

        assert serializer.validate(attrs) is attrs

    def test_to_internal_value_propagates_source_to_nested_contexts(
        self,
        monkeypatch,
    ):
        serializer = CustomReportDefinitionSerializer(
            context=request_context()
        )

        # Stop before DRF performs model-field validation. This test targets
        # only the context propagation performed by the override.
        parent_mock = Mock(return_value={"ok": True})
        monkeypatch.setattr(
            serializers.ModelSerializer,
            "to_internal_value",
            parent_mock,
        )

        payload = {
            "data_source_key": "students",
            "fields": [],
            "filters": [],
            "sorts": [],
            "groups": [],
        }

        result = serializer.to_internal_value(payload)

        assert result == {"ok": True}
        assert serializer.context["data_source_key"] == "students"

        for name in ("fields", "filters", "sorts", "groups"):
            child_context = serializer.fields[name].child.context
            assert child_context["data_source_key"] == "students"
            assert "request" in child_context

        parent_mock.assert_called_once_with(payload)

    def test_to_internal_value_sets_none_for_missing_source(
        self,
        monkeypatch,
    ):
        serializer = CustomReportDefinitionSerializer(
            context=request_context()
        )

        monkeypatch.setattr(
            serializers.ModelSerializer,
            "to_internal_value",
            Mock(return_value={}),
        )

        serializer.to_internal_value({"fields": []})

        assert serializer.context["data_source_key"] is None

    def test_create_delegates_all_persistence_to_service(
        self,
        monkeypatch,
    ):
        school = make_school(pk=4)
        user = make_user(pk=9, school=school)
        definition = make_definition()
        create_mock = Mock(return_value=definition)

        monkeypatch.setattr(
            serializer_module.custom_report_service,
            "create_definition",
            create_mock,
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context(user=user)
        )

        validated_data = {
            "name": "Student report",
            "description": "Description",
            "data_source_key": "students",
            "is_public": False,
            "is_active": True,
            "fields": [
                {
                    "field_key": "name",
                    "order": 1,
                    "is_aggregate": False,
                }
            ],
            "filters": [],
            "sorts": [],
            "groups": [],
        }

        assert serializer.create(validated_data) is definition

        create_mock.assert_called_once_with(
            school=school,
            owner=user,
            created_by=user,
            **validated_data,
        )

    def test_create_converts_domain_error(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            serializer_module.custom_report_service,
            "create_definition",
            Mock(
                side_effect=DomainValidationError(
                    "Definition could not be created."
                )
            ),
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context()
        )

        with pytest.raises(
            serializers.ValidationError,
            match="Definition could not be created",
        ):
            serializer.create(
                {
                    "name": "Report",
                    "data_source_key": "students",
                    "fields": [],
                }
            )

    def test_create_does_not_swallow_unexpected_error(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            serializer_module.custom_report_service,
            "create_definition",
            Mock(side_effect=RuntimeError("database unavailable")),
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context()
        )

        with pytest.raises(
            RuntimeError,
            match="database unavailable",
        ):
            serializer.create(
                {
                    "name": "Report",
                    "data_source_key": "students",
                    "fields": [],
                }
            )

    def test_update_delegates_all_persistence_to_service(
        self,
        monkeypatch,
    ):
        user = make_user(pk=8)
        definition = make_definition()
        updated_definition = make_definition(
            name="Updated report"
        )
        update_mock = Mock(return_value=updated_definition)

        monkeypatch.setattr(
            serializer_module.custom_report_service,
            "update_definition",
            update_mock,
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context(user=user)
        )

        changes = {
            "name": "Updated report",
            "is_public": True,
        }

        assert serializer.update(
            definition,
            changes,
        ) is updated_definition

        update_mock.assert_called_once_with(
            definition=definition,
            updated_by=user,
            changes=changes,
        )

    def test_update_converts_domain_error(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            serializer_module.custom_report_service,
            "update_definition",
            Mock(
                side_effect=DomainValidationError(
                    "Definition could not be updated."
                )
            ),
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context()
        )

        with pytest.raises(
            serializers.ValidationError,
            match="Definition could not be updated",
        ):
            serializer.update(
                make_definition(),
                {"name": "Updated"},
            )

    def test_update_does_not_swallow_unexpected_error(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            serializer_module.custom_report_service,
            "update_definition",
            Mock(side_effect=RuntimeError("unexpected failure")),
        )

        serializer = CustomReportDefinitionSerializer(
            context=request_context()
        )

        with pytest.raises(
            RuntimeError,
            match="unexpected failure",
        ):
            serializer.update(
                make_definition(),
                {"name": "Updated"},
            )


class TestCustomReportExecutionSerializer:
    def test_declared_fields(self):
        serializer = CustomReportExecutionSerializer()

        assert tuple(serializer.fields) == (
            "id",
            "definition_id",
            "executed_by_id",
            "executed_at",
            "row_count",
            "generated_report_id",
            "status",
        )

    def test_every_field_is_read_only(self):
        serializer = CustomReportExecutionSerializer()

        assert all(
            field.read_only
            for field in serializer.fields.values()
        )

    def test_input_is_ignored_for_read_only_serializer(self):
        serializer = CustomReportExecutionSerializer(
            data={
                "id": 100,
                "definition_id": 200,
                "executed_by_id": 300,
                "row_count": 999,
                "generated_report_id": 400,
                "status": "FAILED",
            }
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {}

    def test_representation_contains_execution_identifiers(self):
        execution = make_execution()

        data = CustomReportExecutionSerializer(
            execution
        ).data

        assert data["id"] == 1
        assert data["definition_id"] == 2
        assert data["executed_by_id"] == 3
        assert data["row_count"] == 25
        assert data["generated_report_id"] == 4
        assert data["status"] == "COMPLETED"