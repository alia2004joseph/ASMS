"""
Production API views for performance history and academic-risk assessment.

The view layer only validates transport-level query parameters, enforces
permissions, and delegates all academic calculations and cross-app lookups
to performance_history_service.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.performance_history_serializers import (
    AcademicRiskResponseSerializer,
    PerformanceHistoryPointSerializer,
)
from reports.services import performance_history_service


MAX_TERM_IDS = 100


class _PerformanceQuerySerializer(serializers.Serializer):
    """
    Transport-only validation for optional term filtering.

    Accepts either:
    - ?term_ids=1,2,3
    - ?term_ids=1&term_ids=2&term_ids=3
    """

    term_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
        max_length=MAX_TERM_IDS,
    )

    def validate_term_ids(self, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError(
                "Duplicate term IDs are not allowed."
            )
        return value


def _normalise_term_ids(query_params: Any) -> dict[str, Any]:
    raw_values = query_params.getlist("term_ids")

    if not raw_values:
        return {}

    values: list[str] = []

    for raw_value in raw_values:
        values.extend(
            item.strip()
            for item in raw_value.split(",")
            if item.strip()
        )

    return {"term_ids": values}


class PerformanceHistoryViewSet(viewsets.ViewSet):
    """
    Read-only endpoints for a student's authoritative academic history
    and academic-risk assessment.
    """

    permission_classes = (
        IsAuthenticated,
        BaseReportPermission,
    )

    def get_serializer_context(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "view": self,
        }

    def _validated_term_ids(self, request) -> list[int] | None:
        query_serializer = _PerformanceQuerySerializer(
            data=_normalise_term_ids(request.query_params),
            context=self.get_serializer_context(),
        )
        query_serializer.is_valid(raise_exception=True)
        return query_serializer.validated_data.get("term_ids")

    @action(
        detail=True,
        methods=("get",),
        url_path="history",
    )
    def history(self, request, pk=None):
        term_ids = self._validated_term_ids(request)

        history = performance_history_service.get_performance_history(
            school=request.user.school,
            requested_by=request.user,
            student_id=int(pk),
            term_ids=term_ids,
        )

        serializer = PerformanceHistoryPointSerializer(
            history,
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=("get",),
        url_path="risk",
    )
    def risk(self, request, pk=None):
        term_ids = self._validated_term_ids(request)

        result = performance_history_service.assess_academic_risk(
            school=request.user.school,
            requested_by=request.user,
            student_id=int(pk),
            term_ids=term_ids,
        )

        serializer = AcademicRiskResponseSerializer(
            result,
            context=self.get_serializer_context(),
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )