# communications/models.py

import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from accounts.models import User

ALLOWED_ATTACHMENT_EXTENSIONS = [
    "pdf",
    "docx",
    "png",
    "jpg",
    "jpeg",
]

MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def communication_attachment_path(instance, filename):
    school_id = instance.communication.school_id
    communication_id = instance.communication_id or "pending"
    return f"communications/{school_id}/{communication_id}/{filename}"


class Communication(models.Model):
    """
    An official school communication: an announcement, notice, reminder or
    emergency broadcast targeted at some audience within a single school.

    Recipient/delivery records are created only at publish time, from a
    frozen resolution of the audience — later classroom or role changes
    must not silently rewrite an already-published communication's
    delivery history.
    """

    class CommunicationType(models.TextChoices):
        ANNOUNCEMENT = "announcement", "Announcement"
        NOTICE = "notice", "Notice"
        REMINDER = "reminder", "Reminder"
        EMERGENCY = "emergency", "Emergency"
        ACADEMIC = "academic", "Academic"
        FINANCE = "finance", "Finance"
        ATTENDANCE = "attendance", "Attendance"
        TIMETABLE = "timetable", "Timetable"
        EVENT = "event", "Event"
        GENERAL = "general", "General"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        PARTIALLY_DELIVERED = "partially_delivered", "Partially delivered"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        REJECTED = "rejected", "Rejected"

    class AudienceType(models.TextChoices):
        SCHOOL = "school", "Entire school"
        ALL_STUDENTS = "all_students", "All students"
        ALL_GUARDIANS = "all_guardians", "All guardians"
        ALL_TEACHERS = "all_teachers", "All teachers"
        ALL_ADMINS = "all_admins", "All administrators"
        ALL_ACCOUNTANTS = "all_accountants", "All accountants"
        CLASSROOMS = "classrooms", "Selected classrooms"
        USERS = "users", "Selected users"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="communications",
    )

    title = models.CharField(max_length=200)
    body = models.TextField()

    communication_type = models.CharField(
        max_length=20,
        choices=CommunicationType.choices,
        default=CommunicationType.GENERAL,
    )

    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )

    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="communications_created",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="communications_approved",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)

    audience_type = models.CharField(
        max_length=20,
        choices=AudienceType.choices,
    )
    target_classrooms = models.ManyToManyField(
        "academics.Classroom",
        related_name="targeted_communications",
        blank=True,
    )
    target_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="targeted_communications",
        blank=True,
    )
    include_guardians_of_targets = models.BooleanField(
        default=False,
        help_text=(
            "When targeting students (directly or via classrooms), also "
            "notify their linked guardians."
        ),
    )

    channels = models.JSONField(
        default=list,
        blank=True,
        help_text="Delivery channels requested, e.g. ['in_app', 'email'].",
    )

    allow_replies = models.BooleanField(default=False)
    requires_acknowledgement = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)

    scheduled_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    recipient_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-created_at"]
        indexes = [
            models.Index(fields=["school", "status", "created_at"]),
            models.Index(fields=["school", "scheduled_at"]),
        ]

    def clean(self):
        errors = {}

        if self.communication_type == self.CommunicationType.EMERGENCY:
            if self.priority != self.Priority.URGENT:
                errors["priority"] = (
                    "Emergency communications must use urgent priority."
                )

        if (
            self.status == self.Status.REJECTED
            and not self.rejection_reason
        ):
            errors["rejection_reason"] = (
                "A rejection reason is required when rejecting a communication."
            )

        if self.scheduled_at and self.published_at:
            if self.scheduled_at > self.published_at:
                errors["scheduled_at"] = (
                    "A communication cannot be published before its schedule."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(
            exclude=["target_classrooms", "target_users"],
            validate_unique=False,
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} — {self.school.name}"


class CommunicationAttachment(models.Model):
    communication = models.ForeignKey(
        Communication,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    file = models.FileField(
        upload_to=communication_attachment_path,
        validators=[FileExtensionValidator(ALLOWED_ATTACHMENT_EXTENSIONS)],
    )
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="communication_attachments",
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        errors = {}

        if self.file:
            ext = os.path.splitext(self.file.name)[1].lstrip(".").lower()
            if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
                errors["file"] = "This attachment type is not allowed."

            size = getattr(self.file, "size", None)
            if size and size > MAX_ATTACHMENT_SIZE_BYTES:
                errors["file"] = "Attachment exceeds the maximum allowed size."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.original_filename or self.file.name


class CommunicationRecipient(models.Model):
    """
    One delivery record per (communication, recipient, channel).

    Created as a frozen snapshot when a communication is published, so
    subsequent roster/classroom changes never rewrite delivery history.
    """

    class Channel(models.TextChoices):
        IN_APP = "in_app", "In-app"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"
        READ = "read", "Read"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"

    communication = models.ForeignKey(
        Communication,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="communication_deliveries",
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)

    status = models.CharField(
        max_length=15,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True,
    )

    queued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    failure_reason = models.CharField(max_length=255, blank=True)
    provider_message_id = models.CharField(max_length=100, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-communication_id", "recipient_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["communication", "recipient", "channel"],
                name="unique_delivery_per_communication_recipient_channel",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__gte=0),
                name="communication_recipient_attempt_count_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["recipient", "status"]),
            models.Index(fields=["communication", "recipient"]),
        ]

    def mark_read(self):
        if self.read_at is not None:
            return
        now = timezone.now()
        self.read_at = now
        if self.status in (
            self.DeliveryStatus.SENT,
            self.DeliveryStatus.DELIVERED,
        ):
            self.status = self.DeliveryStatus.READ
        self.save(update_fields=["read_at", "status"])

    def mark_acknowledged(self):
        if self.acknowledged_at is not None:
            return
        now = timezone.now()
        if self.read_at is None:
            self.read_at = now
        self.acknowledged_at = now
        self.status = self.DeliveryStatus.ACKNOWLEDGED
        self.save(update_fields=["read_at", "acknowledged_at", "status"])

    def __str__(self):
        return f"{self.communication_id} → {self.recipient_id} ({self.channel})"


class CommunicationTemplate(models.Model):
    class Category(models.TextChoices):
        FEE_REMINDER = "fee_reminder", "Fee reminder"
        ATTENDANCE_ALERT = "attendance_alert", "Attendance alert"
        TIMETABLE_CHANGE = "timetable_change", "Timetable change"
        EXAM_REMINDER = "exam_reminder", "Examination reminder"
        SCHOOL_CLOSURE = "school_closure", "School closure"
        MEETING = "meeting", "Meeting"
        REPORT_AVAILABLE = "report_available", "Report availability"
        CERTIFICATE_AVAILABLE = "certificate_available", "Certificate availability"
        DISCIPLINARY = "disciplinary", "Disciplinary notice"
        EMERGENCY = "emergency", "Emergency notice"
        GENERAL = "general", "General announcement"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="communication_templates",
    )
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=30, choices=Category.choices)

    subject_template = models.CharField(max_length=200)
    body_template = models.TextField()
    allowed_variables = models.JSONField(default=list, blank=True)

    channel = models.CharField(
        max_length=10,
        choices=CommunicationRecipient.Channel.choices,
        default=CommunicationRecipient.Channel.IN_APP,
    )

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="communication_templates_created",
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["school", "category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_template_name_per_school",
            )
        ]
        indexes = [
            models.Index(fields=["school", "category", "is_active"]),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} — {self.school.name}"


class NotificationPreference(models.Model):
    """
    Per-user optional-channel preferences.

    Mandatory categories (emergency broadcasts) bypass these preferences
    by policy in the delivery service — they are never suppressed here.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )

    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=False)

    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    digest_enabled = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences — {self.user}"
