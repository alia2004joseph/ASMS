from django.shortcuts import get_object_or_404

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from reports.models.certificates import Certificate, CertificateTemplate
from reports.permissions.report_permissions import (
    BaseReportPermission,
    CanManageSignatures,
)
from reports.serializers.certificate_serializers import (
    CertificateIssueRequestSerializer,
    CertificateRevokeRequestSerializer,
    CertificateSerializer,
    CertificateTemplateSerializer,
    CertificateVerifyResponseSerializer,
)
from reports.services import certificate_service


class CertificateTemplateViewSet(viewsets.ModelViewSet):
    """
    Certificate template management.

    All create/update/delete logic is delegated to the serializer,
    which delegates to certificate_service.
    """

    serializer_class = CertificateTemplateSerializer
    permission_classes = [IsAuthenticated, CanManageSignatures]

    def get_queryset(self):
        return (
            CertificateTemplate.objects
            .filter(school=self.request.user.school)
            .order_by("name")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class CertificateViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Certificate API.

    Views contain no business logic.

    Services perform all work.
    """

    permission_classes = [
        IsAuthenticated,
        BaseReportPermission,
    ]

    queryset = (
        Certificate.objects
        .select_related(
            "student",
            "school",
        )
        .filter(is_latest=True)
    )

    serializer_class = CertificateSerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(
                school=self.request.user.school,
            )
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_serializer_class(self):

        if self.action == "create":
            return CertificateIssueRequestSerializer

        if self.action == "revoke":
            return CertificateRevokeRequestSerializer

        if self.action == "verify":
            return CertificateVerifyResponseSerializer

        return CertificateSerializer

    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(
            data=request.data,
            context=self.get_serializer_context(),
        )

        serializer.is_valid(raise_exception=True)

        certificate = serializer.save()

        output = CertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )

        return Response(
            output.data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):

        queryset = certificate_service.list_certificates(
            school=request.user.school,
            student_id=request.query_params.get("student_id"),
            user=request.user,
        )

        serializer = CertificateSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
    )
    def revoke(self, request, pk=None):

        certificate = get_object_or_404(
            self.get_queryset(),
            pk=pk,
        )

        self.check_object_permissions(
            request,
            certificate,
        )

        serializer = self.get_serializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "certificate": certificate,
            },
        )

        serializer.is_valid(raise_exception=True)

        certificate = serializer.save()

        output = CertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )

        return Response(output.data)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"verify/(?P<code>[^/.]+)",
        permission_classes=[AllowAny],
    )
    def verify(self, request, code=None):

        result = certificate_service.verify_certificate(
            code=code,
        )

        serializer = CertificateVerifyResponseSerializer(result)

        return Response(serializer.data)