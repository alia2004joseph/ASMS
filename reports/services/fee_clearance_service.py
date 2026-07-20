import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from reports.constants import (
    ClearanceStatus,
    VerificationResult,
)
from reports.exceptions import (
    NotEligibleError,
    ValidationError,
)
from reports.models.fee_clearance import FeeClearanceCertificate
from reports.services import (
    finance_adapter,
    versioning_service,
)
from reports.services.qrcode_service import (
    generate_verification_code,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClearanceEligibility:
    status: str
    outstanding_balance: Decimal
    cleared_amount: Decimal


def _validate_context(
    *,
    student,
    school,
    academic_year=None,
    term=None,
    issued_by=None,
):
    if student.school_id != school.pk:
        raise ValidationError(
            "Student belongs to another school."
        )

    if academic_year is not None and academic_year.school_id != school.pk:
        raise ValidationError(
            "Academic year belongs to another school."
        )

    if term is not None and term.school_id != school.pk:
        raise ValidationError(
            "Academic term belongs to another school."
        )

    if (
        issued_by is not None
        and hasattr(issued_by, "school_id")
        and issued_by.school_id is not None
        and issued_by.school_id != school.pk
        and not issued_by.is_superuser
    ):
        raise ValidationError(
            "Issuing user belongs to another school."
        )

    if (
        issued_by is not None
        and hasattr(issued_by, "is_active")
        and not issued_by.is_active
    ):
        raise ValidationError(
            "Inactive users cannot issue certificates."
        )


def _certificate_number(
    *,
    school,
    academic_year,
    term,
):
    return (
        f"FC-"
        f"{school.pk}-"
        f"{academic_year.pk}-"
        f"{term.pk}-"
        f"{uuid.uuid4().hex[:12].upper()}"
    )


def check_eligibility(
    *,
    student,
    term,
    override_threshold=Decimal("0.00"),
):
    summary = finance_adapter.get_student_balance_summary(
        student,
        term,
    )

    try:
        outstanding = Decimal(summary["outstanding_balance"])
        paid = Decimal(summary["paid_total"])
    except (KeyError, TypeError):
        raise ValidationError(
            "Finance adapter returned an invalid balance summary."
        )

    if outstanding < 0:
        outstanding = Decimal("0.00")

    if paid < 0:
        raise ValidationError(
            "Paid amount cannot be negative."
        )

    if outstanding <= Decimal("0.00"):
        status = ClearanceStatus.CLEARED
    elif outstanding <= override_threshold:
        status = ClearanceStatus.CLEARED_WITH_OVERRIDE
    else:
        status = ClearanceStatus.NOT_CLEARED

    return ClearanceEligibility(
        status=status,
        outstanding_balance=outstanding,
        cleared_amount=paid,
    )


@transaction.atomic
def issue_certificate(
    *,
    student,
    academic_year,
    term,
    school,
    issued_by,
    admin_override=False,
    override_reason="",
    override_by=None,
    override_threshold=Decimal("0.00"),
):
    _validate_context(
        student=student,
        school=school,
        academic_year=academic_year,
        term=term,
        issued_by=issued_by,
    )

    FeeClearanceCertificate.objects.select_for_update().filter(
        school=school,
        student=student,
        academic_year=academic_year,
        term=term,
        is_latest=True,
        is_revoked=False,
    )

    eligibility = check_eligibility(
        student=student,
        term=term,
        override_threshold=override_threshold,
    )

    if (
        eligibility.status == ClearanceStatus.NOT_CLEARED
        and not admin_override
    ):
        raise NotEligibleError(
            f"Outstanding balance: {eligibility.outstanding_balance}"
        )

    final_status = eligibility.status

    if admin_override and final_status == ClearanceStatus.NOT_CLEARED:
        if not override_reason.strip():
            raise ValidationError(
                "override_reason is required."
            )

        final_status = (
            ClearanceStatus.CLEARED_WITH_OVERRIDE
        )

    certificate = FeeClearanceCertificate(
        school=school,
        student=student,
        academic_year=academic_year,
        term=term,
        cleared_amount=eligibility.cleared_amount,
        outstanding_balance=eligibility.outstanding_balance,
        clearance_status=final_status,
        certificate_number=_certificate_number(
            school=school,
            academic_year=academic_year,
            term=term,
        ),
        verification_code=generate_verification_code(),
        override_reason=(
            override_reason if admin_override else ""
        ),
        override_by=(
            override_by if admin_override else None
        ),
        issued_by=issued_by,
        issued_at=timezone.now(),
    )

    certificate.full_clean()
    certificate.save()

    logger.info(
        "Fee clearance certificate %s issued.",
        certificate.certificate_number,
    )

    return certificate


@transaction.atomic
def regenerate_certificate(
    *,
    previous,
    reason,
    generated_by,
):
    logger.info(
        "Regenerating fee clearance certificate %s.",
        previous.certificate_number,
    )

    return versioning_service.create_new_version(
        previous_instance=previous,
        reason=reason,
        generated_by=generated_by,
        extra_fields={
            "certificate_number": (
                f"{previous.certificate_number}"
                f"-R{previous.version + 1}"
            ),
            "verification_code": (
                generate_verification_code()
            ),
        },
    )


@transaction.atomic
def revoke_certificate(
    *,
    certificate,
    reason,
    revoked_by,
):
    if certificate.is_revoked:
        raise ValidationError(
            "Certificate has already been revoked."
        )

    logger.warning(
        "Fee clearance certificate %s revoked.",
        certificate.certificate_number,
    )

    return versioning_service.revoke(
        instance=certificate,
        reason=reason,
        revoked_by=revoked_by,
    )


def verify(verification_code):
    certificate = (
        FeeClearanceCertificate.objects
        .select_related(
            "student",
            "school",
        )
        .filter(
            verification_code=verification_code,
        )
        .first()
    )

    if certificate is None:
        return {
            "result": VerificationResult.NOT_FOUND,
        }

    if certificate.is_revoked:
        return {
            "result": VerificationResult.REVOKED,
            "certificate_number": (
                certificate.certificate_number
            ),
        }

    if not certificate.is_latest:
        return {
            "result": VerificationResult.SUPERSEDED,
            "certificate_number": (
                certificate.certificate_number
            ),
        }

    return {
        "result": VerificationResult.VALID,
        "certificate_number": (
            certificate.certificate_number
        ),
        "clearance_status": (
            certificate.clearance_status
        ),
        "issued_at": certificate.issued_at,
    }