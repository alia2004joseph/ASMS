# communications/admin.py

from django.contrib import admin

from .models import (
    Communication,
    CommunicationAttachment,
    CommunicationRecipient,
    CommunicationTemplate,
    NotificationPreference,
)


class CommunicationAttachmentInline(admin.TabularInline):
    model = CommunicationAttachment
    extra = 0


@admin.register(Communication)
class CommunicationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "school",
        "communication_type",
        "priority",
        "status",
        "audience_type",
        "created_by",
        "published_at",
    )
    list_filter = ("school", "communication_type", "priority", "status", "audience_type")
    search_fields = ("title", "body")
    inlines = [CommunicationAttachmentInline]


@admin.register(CommunicationRecipient)
class CommunicationRecipientAdmin(admin.ModelAdmin):
    list_display = ("communication", "recipient", "channel", "status", "read_at", "acknowledged_at")
    list_filter = ("channel", "status")
    search_fields = ("recipient__email",)


@admin.register(CommunicationTemplate)
class CommunicationTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "category", "channel", "is_active")
    list_filter = ("school", "category", "is_active")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "in_app_enabled", "email_enabled", "sms_enabled", "whatsapp_enabled")
