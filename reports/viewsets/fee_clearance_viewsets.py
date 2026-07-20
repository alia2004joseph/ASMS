"""
Production API views for fee-clearance certificates.

Views remain thin:
- permissions authorize access;
- serializers validate input and delegate writes to services;
- services own business rules and cross-app integrations;
- querysets enforce school isolation.
"""

from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from reports.models.fee_clearance import FeeClearanceCertificate
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.fee_clearance_serializers import (
    FeeClearanceCertificateSerializer,
    FeeClearanceIssueRequestSerializer,
    FeeClearanceRegenerateRequestSerializer,
    FeeClearanceRevokeRequestSerializer,
    FeeClearanceVerifyResponseSerializer,
)
from reports.services import fee_clearance_service


class FeeClearanceCertificateViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Issue, list, regenerate, revoke, and verify fee-clearance certificates.
    """

    permission_classes = (
        IsAuthenticated,
        BaseReportPermission,
    )

    queryset = (
        FeeClearanceCertificate.objects
        .select_related(
            "school",
            "student",
            "academic_year",
            "term",
            "issued_by",
            "revoked_by",
        )
        .filter(is_latest=True)
        .order_by("-issued_at", "-pk")
    )

    serializer_class = FeeClearanceCertificateSerializer

    def get_queryset(self):
        user = self.request.user

        queryset = super().get_queryset()

        if getattr(user, "is_superuser", False):
            return queryset

        return queryset.filter(school_id=user.school_id)

    def get_serializer_class(self):
        if self.action == "create":
            return FeeClearanceIssueRequestSerializer

        if self.action == "regenerate":
            return FeeClearanceRegenerateRequestSerializer

        if self.action == "revoke":
            return FeeClearanceRevokeRequestSerializer

        if self.action == "verify":
            return FeeClearanceVerifyResponseSerializer

        return FeeClearanceCertificateSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def create(self, request, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        certificate = request_serializer.save()

        response_serializer = FeeClearanceCertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        student_id = request.query_params.get("student_id")

        certificates = fee_clearance_service.list_fee_clearance_certificates(
            school=request.user.school,
            requested_by=request.user,
            student_id=student_id,
            latest_only=True,
        )

        page = self.paginate_queryset(certificates)
        if page is not None:
            serializer = FeeClearanceCertificateSerializer(
                page,
                many=True,
                context=self.get_serializer_context(),
            )
            return self.get_paginated_response(serializer.data)

        serializer = FeeClearanceCertificateSerializer(
            certificates,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @action(
        detail=True,
        methods=("post",),
        url_path="regenerate",
    )
    def regenerate(self, request, pk=None):
        previous = self.get_object()
        self.check_object_permissions(request, previous)

        request_serializer = self.get_serializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "certificate": previous,
            },
        )
        request_serializer.is_valid(raise_exception=True)

        certificate = request_serializer.save(previous=previous)

        response_serializer = FeeClearanceCertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )
        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=("post",),
        url_path="revoke",
    )
    def revoke(self, request, pk=None):
        certificate = self.get_object()
        self.check_object_permissions(request, certificate)

        request_serializer = self.get_serializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "certificate": certificate,
            },
        )
        request_serializer.is_valid(raise_exception=True)

        revoked_certificate = request_serializer.save(
            certificate=certificate,
        )

        response_serializer = FeeClearanceCertificateSerializer(
            revoked_certificate,
            context=self.get_serializer_context(),
        )
        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=("get",),
        url_path=r"verify/(?P<code>[^/.]+)",
        permission_classes=(AllowAny,),
        authentication_classes=(),
    )
    def verify(self, request, code=None):
        result = fee_clearance_service.verify_fee_clearance_certificate(
            code=code,
        )

        serializer = FeeClearanceVerifyResponseSerializer(
            result,
            context=self.get_serializer_context(),
        )
        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )