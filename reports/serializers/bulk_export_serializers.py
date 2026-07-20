from __future__ import annotations

from rest_framework import serializers

from reports.constants import BulkJobType
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.bulk_jobs import (
    BulkExportArchive,
    BulkReportItem,
    BulkReportJob,
)
from reports.services import bulk_export_service


class BulkJobCreateRequestSerializer(serializers.Serializer):
    """
    Input serializer only.

    The authenticated user's school determines the school scope.
    Clients never submit school identifiers.
    """

    job_type = serializers.ChoiceField(
        choices=BulkJobType.choices,
    )

    parameters = serializers.JSONField()

    def validate_parameters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "parameters must be a JSON object."
            )

        allowed = {
            "class_id",
            "student_ids",
            "scope",
        }

        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError(
                f"Unknown parameter(s): {', '.join(sorted(unknown))}."
            )

        supplied = [
            key for key in allowed if key in value
        ]

        if len(supplied) != 1:
            raise serializers.ValidationError(
                "Specify exactly one of "
                "class_id, student_ids or scope."
            )

        if "class_id" in value:
            if not isinstance(value["class_id"], int):
                raise serializers.ValidationError(
                    "class_id must be an integer."
                )

        if "student_ids" in value:
            ids = value["student_ids"]

            if (
                not isinstance(ids, list)
                or not ids
            ):
                raise serializers.ValidationError(
                    "student_ids must be a non-empty list."
                )

            if len(ids) != len(set(ids)):
                raise serializers.ValidationError(
                    "Duplicate student_ids are not allowed."
                )

            if not all(
                isinstance(i, int)
                for i in ids
            ):
                raise serializers.ValidationError(
                    "student_ids must contain integers."
                )

        if "scope" in value:
            if value["scope"] != "SCHOOL":
                raise serializers.ValidationError(
                    "Only SCHOOL is currently supported."
                )

        return value

    def validate(self, attrs):
        request = self.context["request"]

        try:
            bulk_export_service.validate_bulk_request(
                school=request.user.school,
                user=request.user,
                job_type=attrs["job_type"],
                parameters=attrs["parameters"],
            )
        except DomainValidationError as exc:
            raise serializers.ValidationError(str(exc))

        return attrs


class BulkReportItemSerializer(serializers.ModelSerializer):

    generated_report_id = serializers.IntegerField(
        source="generated_report_id",
        read_only=True,
    )

    class Meta:
        model = BulkReportItem

        fields = (
            "id",
            "target_object_id",
            "status",
            "generated_report_id",
            "error_message",
        )

        read_only_fields = fields


class BulkReportJobSerializer(serializers.ModelSerializer):

    items = BulkReportItemSerializer(
        many=True,
        read_only=True,
    )

    progress = serializers.SerializerMethodField()

    class Meta:
        model = BulkReportJob

        fields = (
            "id",
            "job_type",
            "status",
            "total_items",
            "completed_items",
            "failed_items",
            "progress",
            "started_at",
            "finished_at",
            "created_at",
            "items",
        )

        read_only_fields = fields

    def get_progress(self, obj):
        if not obj.total_items:
            return 0

        return round(
            (obj.completed_items / obj.total_items) * 100,
            2,
        )


class BulkExportArchiveSerializer(serializers.ModelSerializer):

    job_id = serializers.IntegerField(
        source="job_id",
        read_only=True,
    )

    class Meta:
        model = BulkExportArchive

        fields = (
            "id",
            "job_id",
            "expires_at",
            "downloaded_count",
            "status",
        )

        read_only_fields = fields