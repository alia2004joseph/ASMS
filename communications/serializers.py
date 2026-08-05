# communications/serializers.py

from rest_framework import serializers

from .models import (
    Communication,
    CommunicationAttachment,
    CommunicationRecipient,
    CommunicationTemplate,
    NotificationPreference,
)


class SchoolIsolationMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if (
            user
            and user.is_authenticated
            and not user.is_superuser
            and "school" in self.fields
        ):
            self.fields["school"].read_only = True


class CommunicationAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunicationAttachment
        fields = [
            "id",
            "communication",
            "file",
            "original_filename",
            "content_type",
            "size_bytes",
            "uploaded_by",
            "created_at",
        ]
        read_only_fields = ["uploaded_by", "content_type", "size_bytes", "created_at"]


class CommunicationRecipientSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(source="recipient.get_full_name", read_only=True)
    recipient_email = serializers.EmailField(source="recipient.email", read_only=True)

    class Meta:
        model = CommunicationRecipient
        fields = [
            "id",
            "recipient",
            "recipient_name",
            "recipient_email",
            "channel",
            "status",
            "queued_at",
            "sent_at",
            "delivered_at",
            "failed_at",
            "read_at",
            "acknowledged_at",
            "failure_reason",
            "attempt_count",
        ]
        read_only_fields = fields


class CommunicationListSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.get_full_name", read_only=True
    )

    class Meta:
        model = Communication
        fields = [
            "id",
            "school",
            "title",
            "communication_type",
            "priority",
            "status",
            "audience_type",
            "is_pinned",
            "requires_acknowledgement",
            "created_by",
            "created_by_name",
            "scheduled_at",
            "published_at",
            "expires_at",
            "recipient_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CommunicationDetailSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    attachments = CommunicationAttachmentSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.get_full_name", read_only=True
    )

    class Meta:
        model = Communication
        fields = [
            "id",
            "school",
            "title",
            "body",
            "communication_type",
            "priority",
            "status",
            "created_by",
            "created_by_name",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "audience_type",
            "target_classrooms",
            "target_users",
            "include_guardians_of_targets",
            "channels",
            "allow_replies",
            "requires_acknowledgement",
            "is_pinned",
            "scheduled_at",
            "published_at",
            "expires_at",
            "cancelled_at",
            "recipient_count",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "created_by",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "published_at",
            "cancelled_at",
            "recipient_count",
            "created_at",
            "updated_at",
        ]

    def validate_target_classrooms(self, classrooms):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and not user.is_superuser:
            for classroom in classrooms:
                if classroom.school_id != user.school_id:
                    raise serializers.ValidationError(
                        "All target classrooms must belong to your school."
                    )
        return classrooms

    def validate_target_users(self, users):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and not user.is_superuser:
            for target in users:
                if target.school_id != user.school_id:
                    raise serializers.ValidationError(
                        "All target users must belong to your school."
                    )
        return users


class ScheduleActionSerializer(serializers.Serializer):
    scheduled_at = serializers.DateTimeField()


class RejectActionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class InboxItemSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="communication.title", read_only=True)
    body = serializers.CharField(source="communication.body", read_only=True)
    communication_type = serializers.CharField(
        source="communication.communication_type", read_only=True
    )
    priority = serializers.CharField(source="communication.priority", read_only=True)
    requires_acknowledgement = serializers.BooleanField(
        source="communication.requires_acknowledgement", read_only=True
    )
    is_pinned = serializers.BooleanField(source="communication.is_pinned", read_only=True)
    created_at = serializers.DateTimeField(
        source="communication.published_at", read_only=True
    )

    class Meta:
        model = CommunicationRecipient
        fields = [
            "id",
            "communication",
            "title",
            "body",
            "communication_type",
            "priority",
            "requires_acknowledgement",
            "is_pinned",
            "status",
            "read_at",
            "acknowledged_at",
            "created_at",
        ]
        read_only_fields = fields


class CommunicationTemplateSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    class Meta:
        model = CommunicationTemplate
        fields = [
            "id",
            "school",
            "name",
            "category",
            "subject_template",
            "body_template",
            "allowed_variables",
            "channel",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "in_app_enabled",
            "email_enabled",
            "sms_enabled",
            "whatsapp_enabled",
            "quiet_hours_start",
            "quiet_hours_end",
            "digest_enabled",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]
