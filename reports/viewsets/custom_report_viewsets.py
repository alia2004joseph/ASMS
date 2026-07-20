from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from reports.permissions.report_permissions import (
    CanUseCustomReportBuilder,
)
from reports.serializers.custom_report_serializers import (
    CustomReportDefinitionSerializer,
    ReportableFieldSerializer,
    ReportableSourceSerializer,
)
from reports.services import (
    custom_report_service,
    report_registry_service,
)
from reports.tasks import execute_custom_report_task


class CustomReportSourceViewSet(viewsets.ViewSet):
    """
    Read-only endpoints exposing the custom report registry.
    """

    permission_classes = [CanUseCustomReportBuilder]

    def get_serializer_context(self):
        return {
            "request": self.request,
        }

    def list(self, request):
        sources = report_registry_service.list_sources(
            user=request.user,
            school=request.user.school,
        )

        serializer = ReportableSourceSerializer(
            sources,
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def fields(self, request, pk=None):

        fields = report_registry_service.list_fields(
            source_key=pk,
            user=request.user,
            school=request.user.school,
        )

        serializer = ReportableFieldSerializer(
            fields,
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(serializer.data)


class CustomReportDefinitionViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    CRUD endpoints for custom report definitions.

    Business logic is entirely delegated to the service layer.
    """

    serializer_class = CustomReportDefinitionSerializer
    permission_classes = [CanUseCustomReportBuilder]

    def get_queryset(self):
        return custom_report_service.list_definitions(
            school=self.request.user.school,
            user=self.request.user,
        )

    def get_serializer_context(self):
        return {
            "request": self.request,
        }

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context=self.get_serializer_context(),
        )

        serializer.is_valid(raise_exception=True)

        definition = serializer.save()

        return Response(
            CustomReportDefinitionSerializer(
                definition,
                context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=kwargs.get("partial", False),
            context=self.get_serializer_context(),
        )

        serializer.is_valid(raise_exception=True)

        definition = serializer.save()

        return Response(
            CustomReportDefinitionSerializer(
                definition,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["post"])
    def preview(self, request, pk=None):
        definition = self.get_object()

        preview = custom_report_service.preview_definition(
            definition=definition,
            user=request.user,
            school=request.user.school,
        )

        return Response(preview)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        definition = self.get_object()

        task = execute_custom_report_task.delay(
            definition.pk,
            request.user.pk,
        )

        return Response(
            {
                "task_id": task.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )