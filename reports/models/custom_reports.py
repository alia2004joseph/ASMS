from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from reports.constants import (
    AggregateFunction,
    FieldDataType,
    FilterOperator,
    GeneratedReportStatus,
    SortDirection,
)
from reports.models.base import AuditableModel, SchoolScopedModel


class CustomReportDefinition(SchoolScopedModel, AuditableModel):
    """
    A saved report definition created through the Custom Report Builder.

    IMPORTANT:
    data_source_key and every field_key stored in child models are opaque
    identifiers. They are never interpreted as raw ORM paths. They must
    always be validated through the report registry before execution.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="custom_reports",
    )

    name = models.CharField(
        max_length=150,
    )

    description = models.TextField(
        blank=True,
        default="",
    )

    data_source_key = models.CharField(
        max_length=100,
        db_index=True,
    )

    is_public = models.BooleanField(
        default=False,
        help_text=(
            "Visible only within the same school. "
            "Never shared across schools."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "owner", "name"],
                name="unique_custom_report_name_per_owner",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "owner"],
                name="custom_report_owner_idx",
            ),
            models.Index(
                fields=["school", "is_public"],
                name="custom_report_public_idx",
            ),
            models.Index(
                fields=["school", "data_source_key"],
                name="custom_report_source_idx",
            ),
        ]

    def __str__(self):
        return self.name


class CustomReportField(models.Model):
    definition = models.ForeignKey(
        CustomReportDefinition,
        on_delete=models.CASCADE,
        related_name="fields",
    )

    field_key = models.CharField(
        max_length=150,
    )

    display_label = models.CharField(
        max_length=150,
    )

    data_type = models.CharField(
        max_length=20,
        choices=FieldDataType.choices,
        default=FieldDataType.STRING,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    is_aggregate = models.BooleanField(
        default=False,
    )

    aggregate_function = models.CharField(
        max_length=10,
        choices=AggregateFunction.choices,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["definition", "field_key"],
                name="unique_custom_report_field",
            ),
        ]

    def clean(self):
        super().clean()

        if self.is_aggregate and not self.aggregate_function:
            raise ValidationError(
                {
                    "aggregate_function":
                    "Aggregate fields require an aggregate function."
                }
            )

        if not self.is_aggregate and self.aggregate_function:
            raise ValidationError(
                {
                    "aggregate_function":
                    "Only aggregate fields may define an aggregate function."
                }
            )

    def __str__(self):
        return self.display_label


class CustomReportFilter(models.Model):
    definition = models.ForeignKey(
        CustomReportDefinition,
        on_delete=models.CASCADE,
        related_name="filters",
    )

    field_key = models.CharField(
        max_length=150,
    )

    operator = models.CharField(
        max_length=20,
        choices=FilterOperator.choices,
    )

    value = models.JSONField()

    is_date_range = models.BooleanField(
        default=False,
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["definition", "field_key"],
                name="custom_filter_field_idx",
            ),
        ]

    def __str__(self):
        return f"{self.field_key} ({self.operator})"


class CustomReportSort(models.Model):
    definition = models.ForeignKey(
        CustomReportDefinition,
        on_delete=models.CASCADE,
        related_name="sorts",
    )

    field_key = models.CharField(
        max_length=150,
    )

    direction = models.CharField(
        max_length=4,
        choices=SortDirection.choices,
        default=SortDirection.ASC,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["definition", "order"],
                name="unique_sort_order",
            ),
        ]

    def __str__(self):
        return f"{self.field_key} ({self.direction})"


class CustomReportGroup(models.Model):
    definition = models.ForeignKey(
        CustomReportDefinition,
        on_delete=models.CASCADE,
        related_name="groups",
    )

    field_key = models.CharField(
        max_length=150,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    show_subtotal = models.BooleanField(
        default=False,
    )

    show_grand_total = models.BooleanField(
        default=False,
    )

    class Meta:
        ordering = ["order"]

        constraints = [
            models.UniqueConstraint(
                fields=["definition", "order"],
                name="unique_group_order",
            ),
        ]

    def __str__(self):
        return self.field_key


class CustomReportExecution(SchoolScopedModel):
    """
    Immutable execution history of a custom report.

    Stores the resolved execution parameters so that the exact report can
    be reproduced later for auditing purposes.
    """

    definition = models.ForeignKey(
        CustomReportDefinition,
        on_delete=models.CASCADE,
        related_name="executions",
    )

    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custom_report_executions",
    )

    executed_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    parameters_snapshot = models.JSONField(
        default=dict,
        blank=True,
    )

    row_count = models.PositiveIntegerField(
        default=0,
    )

    generated_report = models.ForeignKey(
        "reports.GeneratedReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custom_report_executions",
    )

    status = models.CharField(
        max_length=20,
        choices=GeneratedReportStatus.choices,
        default=GeneratedReportStatus.PENDING,
        db_index=True,
    )

    class Meta:
        ordering = ["-executed_at"]

        indexes = [
            models.Index(
                fields=["school", "definition", "-executed_at"],
                name="custom_exec_definition_idx",
            ),
            models.Index(
                fields=["school", "status"],
                name="custom_exec_status_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.definition.name} "
            f"({self.get_status_display()})"
        )