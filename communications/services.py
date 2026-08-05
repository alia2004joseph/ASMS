# communications/services.py

"""
Service layer for the Communications app.

Views/viewsets and serializers must not contain workflow or delivery
logic directly — they call into these functions, which own transactions,
validation of cross-cutting invariants (school isolation, audience
resolution, idempotent delivery) and audit-relevant state transitions.
"""

import logging

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import GuardianStudentLink, StudentProfile, User

from .models import (
    Communication,
    CommunicationRecipient,
    CommunicationTemplate,
)

logger = logging.getLogger(__name__)

TEACHER_BROADCAST_AUDIENCES = {
    Communication.AudienceType.CLASSROOMS,
    Communication.AudienceType.USERS,
}


# ---------------------------------------------------------------------------
# audience_service
# ---------------------------------------------------------------------------

def validate_targeting(communication, target_classrooms=None, target_users=None):
    """
    Ensure every targeted classroom/user belongs to the communication's
    school. Raises ValidationError (DRF) otherwise. Cross-school IDs must
    never be silently dropped or accepted.
    """

    school_id = communication.school_id

    if target_classrooms is not None:
        for classroom in target_classrooms:
            if classroom.school_id != school_id:
                raise ValidationError(
                    "All target classrooms must belong to the "
                    "communication's school."
                )

    if target_users is not None:
        for user in target_users:
            if user.school_id != school_id:
                raise ValidationError(
                    "All target users must belong to the "
                    "communication's school."
                )

    if communication.audience_type == Communication.AudienceType.CLASSROOMS:
        if target_classrooms is not None and len(list(target_classrooms)) == 0:
            raise ValidationError(
                "At least one classroom must be selected for this audience type."
            )

    if communication.audience_type == Communication.AudienceType.USERS:
        if target_users is not None and len(list(target_users)) == 0:
            raise ValidationError(
                "At least one user must be selected for this audience type."
            )


def resolve_recipients(communication):
    """
    Resolve the set of User objects that should receive this
    communication, strictly scoped to the communication's school, with
    de-duplication.

    Returns a dict {user_id: User} for O(1) de-duplication regardless of
    how many targeting rules matched the same person.
    """

    school_id = communication.school_id
    audience = communication.audience_type
    recipients = {}

    def add_queryset(qs):
        for user in qs:
            recipients[user.id] = user

    base_active = User.objects.filter(
        school_id=school_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    )

    if audience == Communication.AudienceType.SCHOOL:
        add_queryset(base_active)

    elif audience == Communication.AudienceType.ALL_STUDENTS:
        add_queryset(base_active.filter(role=User.Role.STUDENT))

    elif audience == Communication.AudienceType.ALL_GUARDIANS:
        add_queryset(base_active.filter(role=User.Role.GUARDIAN))

    elif audience == Communication.AudienceType.ALL_TEACHERS:
        add_queryset(base_active.filter(role=User.Role.TEACHER))

    elif audience == Communication.AudienceType.ALL_ADMINS:
        add_queryset(base_active.filter(role=User.Role.ADMIN))

    elif audience == Communication.AudienceType.ALL_ACCOUNTANTS:
        add_queryset(base_active.filter(role=User.Role.ACCOUNTANT))

    elif audience == Communication.AudienceType.CLASSROOMS:
        classroom_ids = communication.target_classrooms.filter(
            school_id=school_id
        ).values_list("id", flat=True)

        student_user_ids = StudentProfile.objects.filter(
            classroom_id__in=classroom_ids,
            school_id=school_id,
            is_active_student=True,
        ).values_list("user_id", flat=True)

        add_queryset(base_active.filter(id__in=list(student_user_ids)))

        if communication.include_guardians_of_targets:
            guardian_ids = GuardianStudentLink.objects.filter(
                student_id__in=list(student_user_ids),
                can_receive_notifications=True,
            ).values_list("guardian_id", flat=True)
            add_queryset(base_active.filter(id__in=list(guardian_ids)))

    elif audience == Communication.AudienceType.USERS:
        target_ids = communication.target_users.filter(
            school_id=school_id
        ).values_list("id", flat=True)

        add_queryset(base_active.filter(id__in=list(target_ids)))

        if communication.include_guardians_of_targets:
            student_target_ids = communication.target_users.filter(
                school_id=school_id, role=User.Role.STUDENT
            ).values_list("id", flat=True)
            guardian_ids = GuardianStudentLink.objects.filter(
                student_id__in=list(student_target_ids),
                can_receive_notifications=True,
            ).values_list("guardian_id", flat=True)
            add_queryset(base_active.filter(id__in=list(guardian_ids)))

    else:
        raise ValidationError("Unsupported audience type.")

    # Defence in depth: even if a caller bypassed the checks above, never
    # let a recipient from another school slip through.
    stray = [u for u in recipients.values() if u.school_id != school_id]
    if stray:
        raise ValidationError(
            "Audience resolution produced a recipient outside the "
            "communication's school."
        )

    return recipients


def freeze_recipient_snapshot(communication, channels):
    """
    Create (or, if re-run, top up) CommunicationRecipient rows for every
    resolved recipient and requested channel. Idempotent: safe to call
    more than once for the same communication (e.g. on a Celery retry) —
    existing rows are left untouched via get_or_create.
    """

    recipients = resolve_recipients(communication)
    created_count = 0

    for user in recipients.values():
        for channel in channels:
            _, created = CommunicationRecipient.objects.get_or_create(
                communication=communication,
                recipient=user,
                channel=channel,
            )
            if created:
                created_count += 1

    return created_count, len(recipients)


# ---------------------------------------------------------------------------
# communication_service
# ---------------------------------------------------------------------------

def _require_manager_role(user):
    if user.is_superuser:
        return
    if user.role not in (User.Role.ADMIN, User.Role.TEACHER, User.Role.ACCOUNTANT):
        raise PermissionDenied(
            "Only administrators, teachers or accountants may create communications."
        )


def _enforce_role_scope_rules(user, communication):
    """
    Business rules from the permission matrix that depend on the
    communication's own type/audience, not just the endpoint.
    """

    if user.is_superuser or user.role == User.Role.ADMIN:
        return

    if communication.communication_type == Communication.CommunicationType.EMERGENCY:
        raise PermissionDenied(
            "Only school administrators may issue emergency broadcasts."
        )

    if communication.audience_type == Communication.AudienceType.SCHOOL:
        raise PermissionDenied(
            "Only school administrators may target the entire school."
        )

    if user.role == User.Role.ACCOUNTANT:
        if communication.communication_type != Communication.CommunicationType.FINANCE:
            raise PermissionDenied(
                "Accountants may only create finance-related communications."
            )

    if user.role == User.Role.TEACHER:
        if communication.audience_type not in TEACHER_BROADCAST_AUDIENCES:
            raise PermissionDenied(
                "Teachers may only target their own classrooms or selected users."
            )

        if communication.audience_type == Communication.AudienceType.CLASSROOMS:
            from academics.models import ClassroomSubject

            taught_classroom_ids = set(
                ClassroomSubject.objects.filter(
                    teacher=user, is_active=True
                ).values_list("classroom_id", flat=True)
            )
            targeted_ids = set(
                communication.target_classrooms.values_list("id", flat=True)
            )
            if not targeted_ids.issubset(taught_classroom_ids):
                raise PermissionDenied(
                    "Teachers may only target classrooms they teach."
                )


def requires_approval(user, communication):
    if user.is_superuser or user.role == User.Role.ADMIN:
        return False
    return True


def create_draft(user, **fields):
    _require_manager_role(user)

    if not user.is_superuser and "school" in fields:
        fields.pop("school")

    school = user.school if not user.is_superuser else fields.get("school")
    if school is None:
        raise ValidationError("A school is required to create a communication.")

    communication = Communication(
        school=school,
        created_by=user,
        status=Communication.Status.DRAFT,
        **fields,
    )
    communication.save()
    return communication


def update_draft(user, communication, **fields):
    if communication.status not in (
        Communication.Status.DRAFT,
        Communication.Status.REJECTED,
    ):
        raise ValidationError("Only draft or rejected communications can be edited.")

    for key, value in fields.items():
        setattr(communication, key, value)

    if communication.status == Communication.Status.REJECTED:
        communication.status = Communication.Status.DRAFT
        communication.rejection_reason = ""

    communication.save()
    return communication


def submit_for_approval(user, communication):
    if communication.status != Communication.Status.DRAFT:
        raise ValidationError("Only draft communications can be submitted.")

    validate_targeting(
        communication,
        target_classrooms=communication.target_classrooms.all(),
        target_users=communication.target_users.all(),
    )
    _enforce_role_scope_rules(user, communication)

    if requires_approval(user, communication):
        communication.status = Communication.Status.PENDING_APPROVAL
    else:
        communication.status = Communication.Status.DRAFT

    communication.save(update_fields=["status", "updated_at"])
    return communication


def approve(admin_user, communication):
    if admin_user.role != User.Role.ADMIN and not admin_user.is_superuser:
        raise PermissionDenied("Only administrators may approve communications.")

    if communication.status != Communication.Status.PENDING_APPROVAL:
        raise ValidationError("Only communications pending approval can be approved.")

    communication.status = Communication.Status.DRAFT
    communication.approved_by = admin_user
    communication.approved_at = timezone.now()
    communication.save(
        update_fields=["status", "approved_by", "approved_at", "updated_at"]
    )
    return communication


def reject(admin_user, communication, reason):
    if admin_user.role != User.Role.ADMIN and not admin_user.is_superuser:
        raise PermissionDenied("Only administrators may reject communications.")

    if communication.status != Communication.Status.PENDING_APPROVAL:
        raise ValidationError("Only communications pending approval can be rejected.")

    if not reason or not reason.strip():
        raise ValidationError("A rejection reason is required.")

    communication.status = Communication.Status.REJECTED
    communication.approved_by = admin_user
    communication.approved_at = timezone.now()
    communication.rejection_reason = reason.strip()
    communication.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "updated_at",
        ]
    )
    return communication


def schedule(user, communication, scheduled_at):
    if communication.status not in (
        Communication.Status.DRAFT,
        Communication.Status.PENDING_APPROVAL,
    ):
        raise ValidationError("Only draft communications can be scheduled.")

    if requires_approval(user, communication) and communication.status != (
        Communication.Status.PENDING_APPROVAL
    ):
        raise ValidationError("This communication must be approved before scheduling.")

    if scheduled_at <= timezone.now():
        raise ValidationError("The schedule time must be in the future.")

    communication.scheduled_at = scheduled_at
    communication.status = Communication.Status.SCHEDULED
    communication.save(update_fields=["scheduled_at", "status", "updated_at"])
    return communication


@transaction.atomic
def publish(user, communication):
    if communication.status not in (
        Communication.Status.DRAFT,
        Communication.Status.SCHEDULED,
    ):
        raise ValidationError(
            "Only draft or scheduled communications can be published."
        )

    if requires_approval(user, communication) and not communication.approved_at:
        raise ValidationError("This communication must be approved before publishing.")

    validate_targeting(
        communication,
        target_classrooms=communication.target_classrooms.all(),
        target_users=communication.target_users.all(),
    )

    channels = communication.channels or [CommunicationRecipient.Channel.IN_APP]

    communication.status = Communication.Status.PUBLISHING
    communication.save(update_fields=["status", "updated_at"])

    _, recipient_total = freeze_recipient_snapshot(communication, channels)

    communication.recipient_count = recipient_total
    communication.published_at = timezone.now()
    communication.status = Communication.Status.PUBLISHED
    communication.save(
        update_fields=["recipient_count", "published_at", "status", "updated_at"]
    )

    transaction.on_commit(lambda: deliver_communication(communication.id))

    return communication


def cancel(user, communication):
    if communication.status in (
        Communication.Status.CANCELLED,
        Communication.Status.COMPLETED,
        Communication.Status.EXPIRED,
    ):
        raise ValidationError("This communication can no longer be cancelled.")

    communication.status = Communication.Status.CANCELLED
    communication.cancelled_at = timezone.now()
    communication.save(update_fields=["status", "cancelled_at", "updated_at"])
    return communication


def expire_due_communications():
    now = timezone.now()
    due = Communication.objects.filter(
        expires_at__lte=now,
    ).exclude(
        status__in=[
            Communication.Status.EXPIRED,
            Communication.Status.CANCELLED,
            Communication.Status.DRAFT,
        ]
    )
    return due.update(status=Communication.Status.EXPIRED)


# ---------------------------------------------------------------------------
# delivery_service
# ---------------------------------------------------------------------------

def deliver_communication(communication_id):
    """
    Deliver a published communication across all pending recipient
    records. Synchronous for now (no Celery is configured in this
    repository) — see the Communications README for how to move this
    behind a task queue without changing the function's contract.
    """

    communication = Communication.objects.select_related("school").get(
        id=communication_id
    )

    pending = communication.recipients.filter(
        status=CommunicationRecipient.DeliveryStatus.PENDING
    ).select_related("recipient")

    delivered_count = 0
    failed_count = 0

    for record in pending:
        if record.channel == CommunicationRecipient.Channel.IN_APP:
            deliver_in_app(record)
            delivered_count += 1
        elif record.channel == CommunicationRecipient.Channel.EMAIL:
            ok = deliver_email(record, communication)
            if ok:
                delivered_count += 1
            else:
                failed_count += 1
        else:
            record.status = CommunicationRecipient.DeliveryStatus.SKIPPED
            record.failure_reason = f"{record.channel} provider is not configured."
            record.save(update_fields=["status", "failure_reason"])

    total = communication.recipients.count()
    remaining_pending = communication.recipients.filter(
        status=CommunicationRecipient.DeliveryStatus.PENDING
    ).count()

    if remaining_pending == 0:
        communication.status = (
            Communication.Status.COMPLETED
            if failed_count == 0
            else Communication.Status.PARTIALLY_DELIVERED
        )
        communication.save(update_fields=["status", "updated_at"])

    return {"total": total, "delivered": delivered_count, "failed": failed_count}


def deliver_in_app(record):
    now = timezone.now()
    record.status = CommunicationRecipient.DeliveryStatus.DELIVERED
    record.sent_at = now
    record.delivered_at = now
    record.attempt_count += 1
    record.last_attempt_at = now
    record.save(
        update_fields=[
            "status",
            "sent_at",
            "delivered_at",
            "attempt_count",
            "last_attempt_at",
        ]
    )
    return record


def deliver_email(record, communication):
    now = timezone.now()
    record.attempt_count += 1
    record.last_attempt_at = now

    recipient_email = record.recipient.email
    if not recipient_email:
        record.status = CommunicationRecipient.DeliveryStatus.FAILED
        record.failed_at = now
        record.failure_reason = "Recipient has no email address on file."
        record.save(
            update_fields=[
                "status",
                "failed_at",
                "failure_reason",
                "attempt_count",
                "last_attempt_at",
            ]
        )
        return False

    try:
        send_mail(
            subject=f"[{communication.school.name}] {communication.title}",
            message=communication.body,
            from_email=None,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning(
            "Communication %s email delivery failed for recipient %s: %s",
            communication.id,
            record.recipient_id,
            exc,
        )
        record.status = CommunicationRecipient.DeliveryStatus.FAILED
        record.failed_at = now
        record.failure_reason = "Email delivery failed."
        record.save(
            update_fields=[
                "status",
                "failed_at",
                "failure_reason",
                "attempt_count",
                "last_attempt_at",
            ]
        )
        return False

    record.status = CommunicationRecipient.DeliveryStatus.SENT
    record.sent_at = now
    record.save(
        update_fields=["status", "sent_at", "attempt_count", "last_attempt_at"]
    )
    return True


def retry_failed_delivery(communication):
    failed = communication.recipients.filter(
        status=CommunicationRecipient.DeliveryStatus.FAILED
    )
    failed.update(
        status=CommunicationRecipient.DeliveryStatus.PENDING,
        failure_reason="",
    )
    return deliver_communication(communication.id)


# ---------------------------------------------------------------------------
# acknowledgement_service
# ---------------------------------------------------------------------------

def acknowledge(user, communication):
    if not communication.requires_acknowledgement:
        raise ValidationError("This communication does not require acknowledgement.")

    try:
        record = communication.recipients.get(recipient=user, channel="in_app")
    except CommunicationRecipient.DoesNotExist:
        raise PermissionDenied("You are not a recipient of this communication.")

    record.mark_acknowledged()
    return record


def list_pending_acknowledgements(communication):
    return communication.recipients.filter(
        acknowledged_at__isnull=True
    ).select_related("recipient")


# ---------------------------------------------------------------------------
# template_service
# ---------------------------------------------------------------------------

class TemplateVariableError(ValidationError):
    pass


def render_safe_template(template: CommunicationTemplate, context: dict):
    """
    Safe str.format-style substitution restricted to the template's own
    allowed_variables list. Never evaluates arbitrary Python.
    """

    allowed = set(template.allowed_variables or [])
    unknown = set(context.keys()) - allowed
    if unknown:
        raise ValidationError(
            f"Unknown template variables supplied: {', '.join(sorted(unknown))}"
        )

    safe_context = {key: context.get(key, "") for key in allowed}

    try:
        subject = template.subject_template.format(**safe_context)
        body = template.body_template.format(**safe_context)
    except (KeyError, IndexError) as exc:
        raise ValidationError(f"Template rendering failed: missing {exc}") from exc

    return subject, body
