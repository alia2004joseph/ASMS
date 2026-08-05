# communications/views.py

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import (
    Communication,
    CommunicationAttachment,
    CommunicationRecipient,
    CommunicationTemplate,
    NotificationPreference,
)
from .permissions import IsApprovedSchoolMember, IsCommunicationManager
from .serializers import (
    CommunicationAttachmentSerializer,
    CommunicationDetailSerializer,
    CommunicationListSerializer,
    CommunicationRecipientSerializer,
    CommunicationTemplateSerializer,
    InboxItemSerializer,
    NotificationPreferenceSerializer,
    RejectActionSerializer,
    ScheduleActionSerializer,
)


def _school_scoped(queryset, user):
    if not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset
    if user.school_id is None:
        return queryset.none()
    return queryset.filter(school_id=user.school_id)


class CommunicationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsCommunicationManager]

    def get_queryset(self):
        qs = Communication.objects.select_related(
            "school", "created_by", "approved_by"
        ).prefetch_related("attachments")
        return _school_scoped(qs, self.request.user)

    def get_serializer_class(self):
        if self.action == "list":
            return CommunicationListSerializer
        return CommunicationDetailSerializer

    def perform_create(self, serializer):
        validated = dict(serializer.validated_data)
        target_classrooms = validated.pop("target_classrooms", [])
        target_users = validated.pop("target_users", [])

        communication = services.create_draft(self.request.user, **validated)

        if target_classrooms:
            communication.target_classrooms.set(target_classrooms)
        if target_users:
            communication.target_users.set(target_users)

        serializer.instance = communication

    def perform_update(self, serializer):
        instance = serializer.instance
        validated = dict(serializer.validated_data)
        target_classrooms = validated.pop("target_classrooms", None)
        target_users = validated.pop("target_users", None)

        communication = services.update_draft(self.request.user, instance, **validated)

        if target_classrooms is not None:
            communication.target_classrooms.set(target_classrooms)
        if target_users is not None:
            communication.target_users.set(target_users)

        serializer.instance = communication

    def _call_service(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        communication = self.get_object()
        communication = self._call_service(
            services.submit_for_approval, request.user, communication
        )
        return Response(CommunicationDetailSerializer(communication).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        communication = self.get_object()
        communication = self._call_service(services.approve, request.user, communication)
        return Response(CommunicationDetailSerializer(communication).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        communication = self.get_object()
        serializer = RejectActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        communication = self._call_service(
            services.reject, request.user, communication, serializer.validated_data["reason"]
        )
        return Response(CommunicationDetailSerializer(communication).data)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        communication = self.get_object()
        serializer = ScheduleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        communication = self._call_service(
            services.schedule,
            request.user,
            communication,
            serializer.validated_data["scheduled_at"],
        )
        return Response(CommunicationDetailSerializer(communication).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        communication = self.get_object()
        communication = self._call_service(services.publish, request.user, communication)
        return Response(CommunicationDetailSerializer(communication).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        communication = self.get_object()
        communication = self._call_service(services.cancel, request.user, communication)
        return Response(CommunicationDetailSerializer(communication).data)

    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        communication = self.get_object()
        qs = communication.recipients.select_related("recipient").order_by("recipient_id")
        page = self.paginate_queryset(qs)
        serializer = CommunicationRecipientSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="delivery-summary")
    def delivery_summary(self, request, pk=None):
        communication = self.get_object()
        recipients = communication.recipients.all()
        summary = {
            "total": recipients.count(),
            "pending": recipients.filter(
                status=CommunicationRecipient.DeliveryStatus.PENDING
            ).count(),
            "sent": recipients.filter(
                status=CommunicationRecipient.DeliveryStatus.SENT
            ).count(),
            "delivered": recipients.filter(
                status=CommunicationRecipient.DeliveryStatus.DELIVERED
            ).count(),
            "failed": recipients.filter(
                status=CommunicationRecipient.DeliveryStatus.FAILED
            ).count(),
            "read": recipients.filter(read_at__isnull=False).count(),
            "acknowledged": recipients.filter(acknowledged_at__isnull=False).count(),
        }
        return Response(summary)

    @action(detail=True, methods=["get"])
    def acknowledgements(self, request, pk=None):
        communication = self.get_object()
        pending = services.list_pending_acknowledgements(communication)
        serializer = CommunicationRecipientSerializer(pending, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="send-reminder")
    def send_reminder(self, request, pk=None):
        communication = self.get_object()
        if not communication.requires_acknowledgement:
            raise ValidationError("This communication does not require acknowledgement.")
        pending = services.list_pending_acknowledgements(communication)
        count = pending.count()
        return Response({"reminded": count})


class CommunicationAttachmentViewSet(viewsets.ModelViewSet):
    serializer_class = CommunicationAttachmentSerializer
    permission_classes = [IsCommunicationManager]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = CommunicationAttachment.objects.select_related(
            "communication", "communication__school"
        )
        return _school_scoped_by_communication(qs, self.request.user)

    def perform_create(self, serializer):
        communication = serializer.validated_data["communication"]
        user = self.request.user
        if not user.is_superuser and communication.school_id != user.school_id:
            raise PermissionDenied("Cross-school attachments are not allowed.")
        upload = self.request.FILES.get("file")
        extra = {}
        if upload is not None:
            extra["original_filename"] = upload.name
            extra["content_type"] = getattr(upload, "content_type", "") or ""
            extra["size_bytes"] = getattr(upload, "size", 0) or 0
        serializer.save(uploaded_by=user, **extra)


def _school_scoped_by_communication(queryset, user):
    if not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset
    if user.school_id is None:
        return queryset.none()
    return queryset.filter(communication__school_id=user.school_id)


class CommunicationTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = CommunicationTemplateSerializer
    permission_classes = [IsCommunicationManager]

    def get_queryset(self):
        qs = CommunicationTemplate.objects.select_related("school", "created_by")
        return _school_scoped(qs, self.request.user)

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_superuser:
            serializer.save(created_by=user)
        else:
            serializer.save(school=user.school, created_by=user)


class InboxViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InboxItemSerializer
    permission_classes = [IsApprovedSchoolMember]

    def get_queryset(self):
        return (
            CommunicationRecipient.objects.filter(
                recipient=self.request.user,
                channel=CommunicationRecipient.Channel.IN_APP,
            )
            .exclude(status=CommunicationRecipient.DeliveryStatus.SKIPPED)
            .select_related("communication")
            .order_by("-communication__published_at", "-id")
        )

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        record = self.get_object()
        record.mark_read()
        return Response(InboxItemSerializer(record).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        record = self.get_object()
        try:
            services.acknowledge(request.user, record.communication)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        record.refresh_from_db()
        return Response(InboxItemSerializer(record).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        qs = self.get_queryset().filter(read_at__isnull=True)
        count = qs.count()
        for record in qs:
            record.mark_read()
        return Response({"marked_read": count})


class UnreadCountView(APIView):
    permission_classes = [IsApprovedSchoolMember]

    def get(self, request):
        count = CommunicationRecipient.objects.filter(
            recipient=request.user,
            channel=CommunicationRecipient.Channel.IN_APP,
            read_at__isnull=True,
        ).exclude(status=CommunicationRecipient.DeliveryStatus.SKIPPED).count()
        return Response({"unread_count": count})


class NotificationPreferenceView(APIView):
    permission_classes = [IsApprovedSchoolMember]

    def get(self, request):
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return Response(NotificationPreferenceSerializer(pref).data)

    def patch(self, request):
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
