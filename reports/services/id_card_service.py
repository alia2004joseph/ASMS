import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from reports.constants import (
    IDCardStatus,
    GeneratedReportStatus,
    VerificationResult,
)
from reports.exceptions import ValidationError
from reports.models.id_cards import IDCard
from reports.services import versioning_service
from reports.services.qrcode_service import generate_verification_code

logger = logging.getLogger(__name__)


def _validate_issue_request(
    *,
    holder,
    school,
    identification_number,
    valid_from,
    valid_until,
):
    if holder.pk is None:
        raise ValidationError("Holder must be saved.")

    holder_school_id = getattr(holder, "school_id", None)
    if holder_school_id is not None and holder_school_id != school.pk:
        raise ValidationError(
            "Holder belongs to another school."
        )

    if not identification_number.strip():
        raise ValidationError(
            "identification_number is required."
        )

    if valid_until < valid_from:
        raise ValidationError(
            "valid_until cannot be earlier than valid_from."
        )


@transaction.atomic
def issue_id_card(
    *,
    holder,
    holder_type,
    school,
    identification_number,
    role_label="",
    role_context=None,
    valid_from,
    valid_until,
    emergency_contact=None,
):
    _validate_issue_request(
        holder=holder,
        school=school,
        identification_number=identification_number,
        valid_from=valid_from,
        valid_until=valid_until,
    )

    content_type = ContentType.objects.get_for_model(
        holder,
        for_concrete_model=False,
    )

    card = IDCard(
        school=school,
        holder_type=holder_type,
        holder_content_type=content_type,
        holder_object_id=holder.pk,
        identification_number=identification_number.strip(),
        role_label=role_label.strip(),
        role_context=role_context or {},
        valid_from=valid_from,
        valid_until=valid_until,
        verification_code=generate_verification_code(),
        emergency_contact=emergency_contact or {},
        card_status=IDCardStatus.ACTIVE,
        status=GeneratedReportStatus.READY,
    )

    card.full_clean()
    card.save()

    logger.info(
        "Issued ID card %s.",
        card.identification_number,
    )

    return card


@transaction.atomic
def regenerate_id_card(
    *,
    previous,
    reason,
    generated_by,
):
    previous = (
        IDCard.objects
        .select_for_update()
        .get(pk=previous.pk)
    )

    if previous.card_status == IDCardStatus.REVOKED:
        raise ValidationError(
            "A revoked ID card cannot be regenerated."
        )

    if not reason.strip():
        raise ValidationError(
            "regeneration_reason is required."
        )

    previous.card_status = IDCardStatus.REGENERATED
    previous.full_clean()
    previous.save(update_fields=["card_status"])

    logger.info(
        "Regenerated ID card %s.",
        previous.identification_number,
    )

    return versioning_service.create_new_version(
        previous_instance=previous,
        reason=reason,
        generated_by=generated_by,
        extra_fields={
            "verification_code": generate_verification_code(),
            "card_status": IDCardStatus.ACTIVE,
        },
    )


@transaction.atomic
def revoke_id_card(
    *,
    card,
    reason,
    revoked_by,
):
    card = (
        IDCard.objects
        .select_for_update()
        .get(pk=card.pk)
    )

    if card.card_status == IDCardStatus.REVOKED:
        raise ValidationError(
            "ID card has already been revoked."
        )

    card.card_status = IDCardStatus.REVOKED
    card.full_clean()
    card.save(update_fields=["card_status"])

    logger.warning(
        "Revoked ID card %s.",
        card.identification_number,
    )

    return versioning_service.revoke(
        instance=card,
        reason=reason,
        revoked_by=revoked_by,
    )


def verify(verification_code):
    card = (
        IDCard.objects
        .select_related("school")
        .filter(
            verification_code=verification_code,
        )
        .first()
    )

    if card is None:
        return {
            "result": VerificationResult.NOT_FOUND,
        }

    if card.is_revoked or card.card_status == IDCardStatus.REVOKED:
        return {
            "result": VerificationResult.REVOKED,
        }

    if not card.is_latest:
        return {
            "result": VerificationResult.SUPERSEDED,
        }

    today = timezone.localdate()

    if card.valid_until and card.valid_until < today:
        return {
            "result": VerificationResult.EXPIRED,
        }

    return {
        "result": VerificationResult.VALID,
        "holder_type": card.holder_type,
        "identification_number": card.identification_number,
        "valid_until": card.valid_until,
    }