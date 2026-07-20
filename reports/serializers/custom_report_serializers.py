"""
Production serializers for custom report definitions and executions.

These serializers validate input and delegate all persistence to
reports.services.custom_report_service.
"""

from __future__ import annotations

from collections import Counter
from rest_framework import serializers

from reports.constants import AggregateFunction, FilterOperator, SortDirection
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.custom_reports import (
    CustomReportDefinition,
    CustomReportExecution,
    CustomReportField,
    CustomReportFilter,
    CustomReportGroup,
    CustomReportSort,
)
from reports.services import custom_report_service, report_registry_service


class ReportableSourceSerializer(serializers.Serializer):
    source_key = serializers.CharField(read_only=True)
    display_label = serializers.CharField(read_only=True)


class ReportableFieldSerializer(serializers.Serializer):
    field_key = serializers.CharField(read_only=True)
    display_label = serializers.CharField(read_only=True)
    data_type = serializers.CharField(read_only=True)
    is_aggregatable = serializers.BooleanField(read_only=True)


class _RegistryValidatedFieldMixin:
    def _source(self):
        return self.context.get("data_source_key")

    def validate_field_key(self, value):
        user = self.context["request"].user
        if report_registry_service.validate_field_access(
            self._source(), value, user
        ) is None:
            raise serializers.ValidationError(
                f"'{value}' is not an approved reportable field."
            )
        return value


class CustomReportFieldSerializer(_RegistryValidatedFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomReportField
        fields = (
            "field_key",
            "display_label",
            "order",
            "is_aggregate",
            "aggregate_function",
        )

    def validate(self, attrs):
        agg = attrs.get("aggregate_function")
        if attrs.get("is_aggregate") and not agg:
            raise serializers.ValidationError(
                "aggregate_function is required."
            )
        if agg and agg not in AggregateFunction.values:
            raise serializers.ValidationError("Invalid aggregate_function.")
        return attrs


class CustomReportFilterSerializer(_RegistryValidatedFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomReportFilter
        fields = ("field_key", "operator", "value", "is_date_range")

    def validate_operator(self, value):
        if value not in FilterOperator.values:
            raise serializers.ValidationError("Invalid filter operator.")
        return value


class CustomReportSortSerializer(_RegistryValidatedFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomReportSort
        fields = ("field_key", "direction", "order")

    def validate_direction(self, value):
        if value not in SortDirection.values:
            raise serializers.ValidationError("Invalid sort direction.")
        return value


class CustomReportGroupSerializer(_RegistryValidatedFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomReportGroup
        fields = (
            "field_key",
            "order",
            "show_subtotal",
            "show_grand_total",
        )


class CustomReportDefinitionSerializer(serializers.ModelSerializer):
    fields = CustomReportFieldSerializer(many=True)
    filters = CustomReportFilterSerializer(many=True, required=False)
    sorts = CustomReportSortSerializer(many=True, required=False)
    groups = CustomReportGroupSerializer(many=True, required=False)

    class Meta:
        model = CustomReportDefinition
        fields = (
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
        read_only_fields = ("id",)

    def validate_data_source_key(self, value):
        if report_registry_service.validate_source_access(
            value,
            self.context["request"].user,
        ) is None:
            raise serializers.ValidationError(
                "Unavailable data source."
            )
        return value

    def to_internal_value(self, data):
        self.context["data_source_key"] = data.get("data_source_key")
        for n in ("fields", "filters", "sorts", "groups"):
            self.fields[n].child.context.update(self.context)
        return super().to_internal_value(data)

    def validate(self, attrs):
        field_orders = [f["order"] for f in attrs.get("fields", [])]
        dup = [k for k, v in Counter(field_orders).items() if v > 1]
        if dup:
            raise serializers.ValidationError(
                {"fields": "Duplicate field order values."}
            )
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        try:
            return custom_report_service.create_definition(
                school=request.user.school,
                owner=request.user,
                created_by=request.user,
                **validated_data,
            )
        except DomainValidationError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        request = self.context["request"]
        try:
            return custom_report_service.update_definition(
                definition=instance,
                updated_by=request.user,
                changes=validated_data,
            )
        except DomainValidationError as exc:
            raise serializers.ValidationError(str(exc))


class CustomReportExecutionSerializer(serializers.ModelSerializer):
    definition_id = serializers.IntegerField(
        source="definition_id",
        read_only=True,
    )
    executed_by_id = serializers.IntegerField(
        source="executed_by_id",
        read_only=True,
    )
    generated_report_id = serializers.IntegerField(
        source="generated_report_id",
        read_only=True,
    )

    class Meta:
        model = CustomReportExecution
        fields = (
            "id",
            "definition_id",
            "executed_by_id",
            "executed_at",
            "row_count",
            "generated_report_id",
            "status",
        )
        read_only_fields = fields