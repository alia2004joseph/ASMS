import logging
import uuid

from django.db import transaction,IntegrityError
from django.utils import timezone
import secrets



from reports.models.certificates import (
    Certificate,
    CertificateNumberSequence,
    CertificateTemplate,
)

from reports.constants import CertificateStatus, VerificationResult
from reports.exceptions import ValidationError

from reports.services import versioning_service
from reports.services.qrcode_service import generate_verification_code

logger = logging.getLogger(__name__)


def _get_active_template(*, school, certificate_type):
    template = (
        CertificateTemplate.objects
        .filter(
            school=school,
            certificate_type=certificate_type,
            is_active=True,
        )
        .order_by("-version")
        .first()
    )

    if template is None:
        raise ValidationError(
            f"No active template exists for '{certificate_type}'."
        )

    return template


def _validate_request(*, student, school, issued_by, template):
    if student.school_id != school.id:
        raise ValidationError(
            "Student does not belong to the selected school."
        )

    if template.school_id != school.id:
        raise ValidationError(
            "Certificate template belongs to another school."
        )

    if (
        hasattr(issued_by, "school_id")
        and issued_by.school_id is not None
        and issued_by.school_id != school.id
        and not issued_by.is_superuser
    ):
        raise ValidationError(
            "Issuing user belongs to another school."
        )

    if hasattr(issued_by, "is_active") and not issued_by.is_active:
        raise ValidationError(
            "Inactive users cannot issue certificates."
        )


CERTIFICATE_TYPE_CODES = {
    "COMPLETION": "COM",
    "PARTICIPATION": "PAR",
    "GRADUATION": "GRD",
    "TESTIMONIAL": "TES",
}


def _generate_serial_number(*, school, certificate_type):
    """
    Generate a sequential certificate number safely.

    Example:
        CERT-ALIA-2026-COM-000001
    """

    current_year = timezone.localdate().year

    sequence, _ = (
        CertificateNumberSequence.objects
        .select_for_update()
        .get_or_create(
            school=school,
            year=current_year,
            certificate_type=certificate_type,
            defaults={"last_number": 0},
        )
    )

    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])

    school_code = school.code.strip().upper()

    type_code = CERTIFICATE_TYPE_CODES.get(
        certificate_type,
        certificate_type[:3].upper(),
    )

    return (
        f"CERT-{school_code}-{current_year}-"
        f"{type_code}-{sequence.last_number:06d}"
    )

def _generate_verification_code():
    """
    Generate a non-sequential public verification token.

    The value should be difficult to guess and should not expose
    how many certificates the school has issued.
    """

    for _ in range(10):
        code = secrets.token_urlsafe(24)

        if not Certificate.objects.filter(
            verification_code=code,
        ).exists():
            return code

    raise RuntimeError(
        "A unique certificate verification code could not be generated."
    )


@transaction.atomic
def issue_certificate(
    *,
    student,
    school,
    certificate_type,
    issued_by,
    template=None,
):
    """
    Creates a brand-new immutable certificate.

    Existing certificates are never modified.
    """

    if template is None:
        template = _get_active_template(
            school=school,
            certificate_type=certificate_type,
        )

    _validate_request(
        student=student,
        school=school,
        issued_by=issued_by,
        template=template,
    )

    serial_number = _generate_serial_number(
        school=school,
        certificate_type=certificate_type,
    )

    certificate = Certificate(
    school=school,
    student=student,
    certificate_type=certificate_type,
    template=template,
    serial_number=serial_number,
    verification_code=_generate_verification_code(),
    issued_by=issued_by,
    issued_at=timezone.now(),
    status=CertificateStatus.READY,
)

    certificate.full_clean()
    certificate.save()

    logger.info(
        "Certificate %s issued for student %s.",
        certificate.serial_number,
        student.pk,
    )

    return certificate


@transaction.atomic
def revoke_certificate(
    *,
    certificate,
    reason,
    revoked_by,
):
    """
    Revokes a certificate using the centralized versioning service.
    """

    if certificate.is_revoked:
        raise ValidationError(
            "Certificate has already been revoked."
        )

    logger.warning(
        "Certificate %s revoked.",
        certificate.serial_number,
    )

    return versioning_service.revoke(
        instance=certificate,
        reason=reason,
        revoked_by=revoked_by,
    )


def verify(verification_code):
    """
    Public verification endpoint.

    Returns only public information.
    """

    certificate = (
        Certificate.objects
        .filter(
            verification_code=verification_code,
        )
        .select_related(
            "student",
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
        }

    if not certificate.is_latest:
        return {
            "result": VerificationResult.SUPERSEDED,
        }

    return {
        "result": VerificationResult.VALID,
        "serial_number": certificate.serial_number,
        "certificate_type": certificate.certificate_type,
        "issued_at": certificate.issued_at,
        "student_name": str(certificate.student),
    }