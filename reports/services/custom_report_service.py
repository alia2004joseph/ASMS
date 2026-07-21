"""
Secure execution engine for registry-backed custom reports.

Security invariants
-------------------
1. Client-supplied field keys are never used as ORM paths. Every field,
   filter, group, and sort key is resolved through
   ``report_registry_service``.
2. School isolation is applied before user filters and cannot be overridden.
3. Only Django ORM query construction APIs are used. There is no raw SQL,
   ``extra()``, or client-controlled lookup path.
4. Filter values are converted to the registry-declared data type before
   reaching the ORM.
5. Query complexity, preview size, and collection-filter sizes are bounded.

This service intentionally contains no HTTP or serializer logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.apps import apps
from django.core.exceptions import FieldError
from django.db.models import (
    Avg,
    Count,
    Max,
    Min,
    Q,
    QuerySet,
    Sum,
    Value,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from reports.constants import (
    AggregateFunction,
    FieldDataType,
    FilterOperator,
)
from reports.exceptions import RegistryError, ValidationError
from reports.services import report_registry_service as registry_service
from django.db import transaction

from reports.models.custom_reports import (
    CustomReportDefinition,
    CustomReportField,
    CustomReportFilter,
    CustomReportGroup,
    CustomReportSort,
)


DEFAULT_PREVIEW_LIMIT = 50
MAX_PREVIEW_LIMIT = 500
MAX_SELECTED_FIELDS = 50
MAX_FILTERS = 50
MAX_SORT_FIELDS = 10
MAX_GROUP_FIELDS = 10
MAX_IN_VALUES = 1_000
MAX_STRING_FILTER_LENGTH = 2_000

_AGGREGATE_FUNCTIONS = {
    AggregateFunction.SUM: Sum,
    AggregateFunction.AVG: Avg,
    AggregateFunction.COUNT: Count,
    AggregateFunction.MIN: Min,
    AggregateFunction.MAX: Max,
}

_OPERATOR_LOOKUPS = {
    FilterOperator.EQ: "",
    FilterOperator.GT: "__gt",
    FilterOperator.GTE: "__gte",
    FilterOperator.LT: "__lt",
    FilterOperator.LTE: "__lte",
    FilterOperator.IN: "__in",
    FilterOperator.CONTAINS: "__icontains",
}

_ALLOWED_DIRECTIONS = {"ASC", "DESC"}


def _require_mapping(spec: Any, *, label: str, index: int) -> Mapping[str, Any]:
    if not isinstance(spec, Mapping):
        raise ValidationError(f"{label}[{index}] must be an object.")
    return spec


def _bounded_specs(
    specs: Sequence[Mapping[str, Any]] | None,
    *,
    label: str,
    maximum: int,
) -> list[Mapping[str, Any]]:
    if specs is None:
        return []

    if isinstance(specs, (str, bytes)) or not isinstance(specs, Sequence):
        raise ValidationError(f"{label} must be a list.")

    if len(specs) > maximum:
        raise ValidationError(
            f"{label} may contain at most {maximum} entries."
        )

    return [
        _require_mapping(spec, label=label, index=index)
        for index, spec in enumerate(specs)
    ]


def _required_string(
    spec: Mapping[str, Any],
    key: str,
    *,
    context: str,
) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{context}.{key} must be a non-empty string.")
    return value.strip()


def _validate_school_access(*, school: Any, user: Any) -> None:
    if getattr(school, "pk", None) is None:
        raise ValidationError("A persisted school is required.")

    if not getattr(user, "is_authenticated", False):
        raise RegistryError("Authentication is required to execute reports.")

    if not getattr(user, "is_active", False):
        raise RegistryError("Inactive users cannot execute reports.")

    if getattr(user, "is_superuser", False):
        return

    user_school_id = getattr(user, "school_id", None)
    if user_school_id is not None and user_school_id != school.pk:
        raise RegistryError(
            "The selected school is outside the user's permitted scope."
        )


def _resolve_field(*, source_key: str, field_key: str, user: Any):
    field = registry_service.validate_field_access(
        source_key,
        field_key,
        user,
    )
    if field is None:
        raise RegistryError(
            f"Field '{field_key}' is not permitted for this user/source."
        )
    return field


def _coerce_value(data_type: str, raw_value: Any, operator: str) -> Any:
    try:
        if operator == FilterOperator.IN:
            if (
                isinstance(raw_value, (str, bytes))
                or not isinstance(raw_value, Sequence)
            ):
                raise ValueError("IN expects a list of values")
            if not raw_value:
                raise ValueError("IN expects at least one value")
            if len(raw_value) > MAX_IN_VALUES:
                raise ValueError(
                    f"IN accepts at most {MAX_IN_VALUES} values"
                )
            return [
                _coerce_scalar(data_type, value)
                for value in raw_value
            ]

        if operator == FilterOperator.BETWEEN:
            if (
                isinstance(raw_value, (str, bytes))
                or not isinstance(raw_value, Sequence)
                or len(raw_value) != 2
            ):
                raise ValueError("BETWEEN expects exactly two values")

            lower = _coerce_scalar(data_type, raw_value[0])
            upper = _coerce_scalar(data_type, raw_value[1])

            if lower > upper:
                raise ValueError(
                    "BETWEEN lower bound cannot exceed upper bound"
                )

            return lower, upper

        return _coerce_scalar(data_type, raw_value)
    except (
        TypeError,
        ValueError,
        InvalidOperation,
        OverflowError,
    ) as exc:
        raise ValidationError(
            f"Invalid filter value {raw_value!r} for type {data_type}."
        ) from exc


def _coerce_scalar(data_type: str, value: Any) -> Any:
    if data_type in {FieldDataType.STRING, FieldDataType.ENUM}:
        if not isinstance(value, str):
            raise ValueError("expected a string")
        if len(value) > MAX_STRING_FILTER_LENGTH:
            raise ValueError(
                f"string values may not exceed "
                f"{MAX_STRING_FILTER_LENGTH} characters"
            )
        return value

    if data_type == FieldDataType.NUMBER:
        if isinstance(value, bool):
            raise ValueError("boolean is not a number")
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("number must be finite")
        return number

    if data_type == FieldDataType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError("expected a boolean")
        return value

    if data_type == FieldDataType.DATE:
        if isinstance(value, datetime):
            raise ValueError("expected a date, not a datetime")
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            raise ValueError("expected an ISO-8601 date string")
        return date.fromisoformat(value)

    if data_type == FieldDataType.DATETIME:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = parse_datetime(value)
            if parsed is None:
                raise ValueError("expected an ISO-8601 datetime string")
        else:
            raise ValueError("expected a datetime")

        if timezone.is_naive(parsed) and timezone.is_aware(timezone.now()):
            parsed = timezone.make_aware(
                parsed,
                timezone.get_current_timezone(),
            )
        return parsed

    raise ValueError(f"unsupported data type {data_type!r}")


def _validate_operator_for_field(*, field: Any, operator: str) -> None:
    valid_operators = set(_OPERATOR_LOOKUPS) | {
        FilterOperator.NEQ,
        FilterOperator.BETWEEN,
    }
    if operator not in valid_operators:
        raise ValidationError(f"Unsupported filter operator '{operator}'.")

    if (
        operator == FilterOperator.CONTAINS
        and field.data_type
        not in {FieldDataType.STRING, FieldDataType.ENUM}
    ):
        raise ValidationError(
            f"CONTAINS is not valid for field '{field.field_key}'."
        )

    if (
        operator in {
            FilterOperator.GT,
            FilterOperator.GTE,
            FilterOperator.LT,
            FilterOperator.LTE,
            FilterOperator.BETWEEN,
        }
        and field.data_type == FieldDataType.BOOLEAN
    ):
        raise ValidationError(
            f"Ordering operators are not valid for boolean field "
            f"'{field.field_key}'."
        )


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def build_queryset(
    *,
    source_key: str,
    school: Any,
    user: Any,
    field_specs: Sequence[Mapping[str, Any]] | None,
    filter_specs: Sequence[Mapping[str, Any]] | None,
    sort_specs: Sequence[Mapping[str, Any]] | None,
    group_specs: Sequence[Mapping[str, Any]] | None,
) -> tuple[QuerySet, list[str]]:
    """
    Build a school-scoped custom report queryset.

    Returns ``(queryset, output_keys)``. ``output_keys`` contains safe ORM
    value keys and generated aggregate aliases suitable for ``values()`` and
    serialization.
    """
    _validate_school_access(school=school, user=user)

    fields = _bounded_specs(
        field_specs,
        label="field_specs",
        maximum=MAX_SELECTED_FIELDS,
    )
    filters = _bounded_specs(
        filter_specs,
        label="filter_specs",
        maximum=MAX_FILTERS,
    )
    sorts = _bounded_specs(
        sort_specs,
        label="sort_specs",
        maximum=MAX_SORT_FIELDS,
    )
    groups = _bounded_specs(
        group_specs,
        label="group_specs",
        maximum=MAX_GROUP_FIELDS,
    )

    if not fields:
        raise ValidationError("At least one report field must be selected.")

    source = registry_service.validate_source_access(source_key, user)
    if source is None:
        raise RegistryError(
            f"Data source '{source_key}' is not available to this user."
        )

    try:
        model = apps.get_model(source.base_model)
    except (LookupError, ValueError) as exc:
        raise RegistryError(
            f"Registered base model '{source.base_model}' is unavailable."
        ) from exc

    if model is None:
        raise RegistryError(
            f"Registered base model '{source.base_model}' is unavailable."
        )

    # Mandatory school boundary. No client-provided value participates here.
    try:
        queryset = model._default_manager.filter(
            **{source.school_path: school}
        )
    except FieldError as exc:
        raise RegistryError(
            f"Invalid registered school path for source '{source_key}'."
        ) from exc

    resolved_field_specs: list[tuple[Mapping[str, Any], Any]] = []
    selected_keys: set[str] = set()

    for index, spec in enumerate(fields):
        field_key = _required_string(
            spec,
            "field_key",
            context=f"field_specs[{index}]",
        )
        if field_key in selected_keys:
            raise ValidationError(
                f"Field '{field_key}' is selected more than once."
            )
        selected_keys.add(field_key)
        resolved_field_specs.append(
            (
                spec,
                _resolve_field(
                    source_key=source_key,
                    field_key=field_key,
                    user=user,
                ),
            )
        )

    annotations: dict[str, Any] = {}
    aggregate_aliases: dict[tuple[str, str], str] = {}
    aggregate_aliases_by_field: dict[str, list[str]] = {}
    selected_dimension_paths: list[str] = []
    selected_output_keys: list[str] = []

    aggregate_index = 0
    for spec, field in resolved_field_specs:
        is_aggregate = spec.get("is_aggregate", False)
        if not isinstance(is_aggregate, bool):
            raise ValidationError(
                f"is_aggregate for '{field.field_key}' must be boolean."
            )

        if not is_aggregate:
            _append_unique(selected_dimension_paths, field.orm_path)
            _append_unique(selected_output_keys, field.orm_path)
            continue

        function_name = spec.get("aggregate_function")
        if function_name not in _AGGREGATE_FUNCTIONS:
            raise ValidationError(
                f"Unsupported aggregate function '{function_name}'."
            )
        if not field.is_aggregatable:
            raise RegistryError(
                f"Field '{field.field_key}' is not aggregatable."
            )

        aggregate_index += 1
        alias = f"metric_{aggregate_index}"
        aggregate_class = _AGGREGATE_FUNCTIONS[function_name]

        if function_name == AggregateFunction.COUNT:
            annotations[alias] = aggregate_class(field.orm_path)
        else:
            annotations[alias] = aggregate_class(field.orm_path)

        aggregate_aliases[(field.field_key, function_name)] = alias
        aggregate_aliases_by_field.setdefault(
            field.field_key,
            [],
        ).append(alias)
        selected_output_keys.append(alias)

    group_paths: list[str] = []
    for index, spec in enumerate(groups):
        field_key = _required_string(
            spec,
            "field_key",
            context=f"group_specs[{index}]",
        )
        field = _resolve_field(
            source_key=source_key,
            field_key=field_key,
            user=user,
        )
        if getattr(field, "is_groupable", True) is False:
            raise RegistryError(
                f"Field '{field.field_key}' is not groupable."
            )
        _append_unique(group_paths, field.orm_path)

    # All selected dimensions participate in SQL GROUP BY whenever aggregate
    # columns are present. Explicit group fields are also included in output.
    dimension_paths: list[str] = []
    for path in group_paths + selected_dimension_paths:
        _append_unique(dimension_paths, path)

    output_keys: list[str] = []
    for path in dimension_paths:
        _append_unique(output_keys, path)
    for key in selected_output_keys:
        _append_unique(output_keys, key)

    q_object = Q()
    for index, spec in enumerate(filters):
        field_key = _required_string(
            spec,
            "field_key",
            context=f"filter_specs[{index}]",
        )
        operator = _required_string(
            spec,
            "operator",
            context=f"filter_specs[{index}]",
        )
        if "value" not in spec:
            raise ValidationError(
                f"filter_specs[{index}].value is required."
            )

        field = _resolve_field(
            source_key=source_key,
            field_key=field_key,
            user=user,
        )
        if getattr(field, "is_filterable", True) is False:
            raise RegistryError(
                f"Field '{field.field_key}' is not filterable."
            )

        _validate_operator_for_field(field=field, operator=operator)
        coerced = _coerce_value(
            field.data_type,
            spec["value"],
            operator,
        )

        if operator == FilterOperator.NEQ:
            q_object &= ~Q(**{field.orm_path: coerced})
        elif operator == FilterOperator.BETWEEN:
            lower, upper = coerced
            q_object &= Q(
                **{
                    f"{field.orm_path}__gte": lower,
                    f"{field.orm_path}__lte": upper,
                }
            )
        else:
            lookup_suffix = _OPERATOR_LOOKUPS[operator]
            q_object &= Q(
                **{f"{field.orm_path}{lookup_suffix}": coerced}
            )

    if filters:
        queryset = queryset.filter(q_object)

    if annotations:
        if dimension_paths:
            queryset = queryset.values(*dimension_paths).annotate(
                **annotations
            )
        else:
            # A constant grouping key produces exactly one aggregate row while
            # retaining a QuerySet return type.
            queryset = (
                queryset.annotate(_report_group=Value(1))
                .values("_report_group")
                .annotate(**annotations)
                .values(*selected_output_keys)
            )
    else:
        queryset = queryset.values(*output_keys)

    order_fields: list[str] = []
    for index, spec in enumerate(sorts):
        field_key = _required_string(
            spec,
            "field_key",
            context=f"sort_specs[{index}]",
        )
        direction = _required_string(
            spec,
            "direction",
            context=f"sort_specs[{index}]",
        ).upper()

        if direction not in _ALLOWED_DIRECTIONS:
            raise ValidationError(
                f"Unsupported sort direction '{direction}'."
            )

        field = _resolve_field(
            source_key=source_key,
            field_key=field_key,
            user=user,
        )
        if getattr(field, "is_sortable", True) is False:
            raise RegistryError(
                f"Field '{field.field_key}' is not sortable."
            )

        requested_function = spec.get("aggregate_function")
        sort_path: str

        if requested_function:
            sort_path = aggregate_aliases.get(
                (field.field_key, requested_function),
                "",
            )
            if not sort_path:
                raise ValidationError(
                    f"No selected {requested_function} aggregate exists for "
                    f"field '{field.field_key}'."
                )
        else:
            aliases = aggregate_aliases_by_field.get(field.field_key, [])
            if len(aliases) == 1:
                sort_path = aliases[0]
            elif len(aliases) > 1:
                raise ValidationError(
                    f"Sort field '{field.field_key}' has multiple selected "
                    "aggregates; aggregate_function is required."
                )
            else:
                sort_path = field.orm_path
                if annotations and sort_path not in dimension_paths:
                    raise ValidationError(
                        f"Non-aggregate sort field '{field.field_key}' must "
                        "be selected or grouped in an aggregate report."
                    )

        prefix = "-" if direction == "DESC" else ""
        order_fields.append(f"{prefix}{sort_path}")

    if order_fields:
        queryset = queryset.order_by(*order_fields)

    return queryset, output_keys


def execute_preview(
    *,
    source_key: str,
    school: Any,
    user: Any,
    field_specs: Sequence[Mapping[str, Any]] | None,
    filter_specs: Sequence[Mapping[str, Any]] | None,
    sort_specs: Sequence[Mapping[str, Any]] | None,
    group_specs: Sequence[Mapping[str, Any]] | None,
    limit: int = DEFAULT_PREVIEW_LIMIT,
) -> list[dict[str, Any]]:
    """Execute a bounded report preview and return serializable rows."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValidationError("Preview limit must be an integer.")
    if limit < 1 or limit > MAX_PREVIEW_LIMIT:
        raise ValidationError(
            f"Preview limit must be between 1 and {MAX_PREVIEW_LIMIT}."
        )

    queryset, _output_keys = build_queryset(
        source_key=source_key,
        school=school,
        user=user,
        field_specs=field_specs,
        filter_specs=filter_specs,
        sort_specs=sort_specs,
        group_specs=group_specs,
    )
    return list(queryset[:limit])

@transaction.atomic
def create_definition(
    *,
    school,
    owner,
    created_by,
    name,
    description="",
    data_source_key,
    is_public=False,
    is_active=True,
    fields,
    filters=None,
    sorts=None,
    groups=None,
):
    """
    Create a custom report definition and all nested configuration records.
    """

    if school is None or getattr(school, "pk", None) is None:
        raise ValidationError("A persisted school is required.")

    if owner is None or getattr(owner, "pk", None) is None:
        raise ValidationError("A persisted owner is required.")

    if not fields:
        raise ValidationError(
            "At least one report field must be selected."
        )

    source = registry_service.validate_source_access(
        data_source_key,
        owner,
    )
    if source is None:
        raise RegistryError(
            f"Data source '{data_source_key}' is not available."
        )

    definition = CustomReportDefinition.objects.create(
        school=school,
        owner=owner,
        created_by=created_by,
        name=name,
        description=description,
        data_source_key=data_source_key,
        is_public=is_public,
        is_active=is_active,
    )

    CustomReportField.objects.bulk_create(
        [
            CustomReportField(
                definition=definition,
                **field_data,
            )
            for field_data in fields
        ]
    )

    CustomReportFilter.objects.bulk_create(
        [
            CustomReportFilter(
                definition=definition,
                **filter_data,
            )
            for filter_data in (filters or [])
        ]
    )

    CustomReportSort.objects.bulk_create(
        [
            CustomReportSort(
                definition=definition,
                **sort_data,
            )
            for sort_data in (sorts or [])
        ]
    )

    CustomReportGroup.objects.bulk_create(
        [
            CustomReportGroup(
                definition=definition,
                **group_data,
            )
            for group_data in (groups or [])
        ]
    )

    return definition


@transaction.atomic
def update_definition(
    *,
    definition,
    updated_by,
    changes,
):
    """
    Update a custom report definition.

    Nested configuration is replaced only when its corresponding key is
    included in ``changes``.
    """

    if definition is None or getattr(definition, "pk", None) is None:
        raise ValidationError(
            "A persisted report definition is required."
        )

    if updated_by is None or getattr(updated_by, "pk", None) is None:
        raise ValidationError("A persisted user is required.")

    definition = (
        CustomReportDefinition.objects
        .select_for_update()
        .get(pk=definition.pk)
    )

    nested_keys = {
        "fields",
        "filters",
        "sorts",
        "groups",
    }

    scalar_changes = {
        key: value
        for key, value in changes.items()
        if key not in nested_keys
    }

    if "data_source_key" in scalar_changes:
        source = registry_service.validate_source_access(
            scalar_changes["data_source_key"],
            updated_by,
        )
        if source is None:
            raise RegistryError(
                f"Data source "
                f"'{scalar_changes['data_source_key']}' "
                "is not available."
            )

    for field_name, value in scalar_changes.items():
        setattr(definition, field_name, value)

    if hasattr(definition, "updated_by"):
        definition.updated_by = updated_by

    definition.save()

    if "fields" in changes:
        fields = changes["fields"]

        if not fields:
            raise ValidationError(
                "At least one report field must be selected."
            )

        definition.fields.all().delete()

        CustomReportField.objects.bulk_create(
            [
                CustomReportField(
                    definition=definition,
                    **field_data,
                )
                for field_data in fields
            ]
        )

    if "filters" in changes:
        definition.filters.all().delete()

        CustomReportFilter.objects.bulk_create(
            [
                CustomReportFilter(
                    definition=definition,
                    **filter_data,
                )
                for filter_data in changes["filters"]
            ]
        )

    if "sorts" in changes:
        definition.sorts.all().delete()

        CustomReportSort.objects.bulk_create(
            [
                CustomReportSort(
                    definition=definition,
                    **sort_data,
                )
                for sort_data in changes["sorts"]
            ]
        )

    if "groups" in changes:
        definition.groups.all().delete()

        CustomReportGroup.objects.bulk_create(
            [
                CustomReportGroup(
                    definition=definition,
                    **group_data,
                )
                for group_data in changes["groups"]
            ]
        )

    return definition