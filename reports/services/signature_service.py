"""
Production service for resolving and updating document signature assignments.

This module is the authoritative service boundary for:
- selecting the active signature/stamp assignment for a school and document;
- validating signatory, signature, stamp, and assignment validity windows;
- building a safe template context for generated documents;
- updating assignments with immutable audit history.

Templates and document-generation services should call
``build_signature_context()`` rather than querying signature models directly.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.db import transaction
from django.utils import timezone

from reports.exceptions import ValidationError
from reports.models.signatures import (
    DocumentSignatureAssignment,
    SignatureAssignmentHistory,
)


logger = logging.getLogger(__name__)

_ALLOWED_UPDATE_FIELDS = {
    "signatory",
    "signature",
    "stamp",
    "position",
    "is_active",
    "valid_from",
    "valid_until",
}


def _today() -> date:
    return timezone.localdate()


def _is_within_validity(obj: Any, today: date | None = None) -> bool:
    """
    Return whether an object is valid on the supplied local date.

    Missing validity boundaries are treated as open-ended.
    """
    if obj is None:
        return False

    current_date = today or _today()
    valid_from = getattr(obj, "valid_from", None)
    valid_until = getattr(obj, "valid_until", None)

    if valid_from and valid_from > current_date:
        return False
    if valid_until and valid_until < current_date:
        return False
    return True


def _validate_school(school: Any) -> None:
    if getattr(school, "pk", None) is None:
        raise ValidationError("A persisted school is required.")


def _validate_document_type(document_type: str) -> str:
    if not isinstance(document_type, str) or not document_type.strip():
        raise ValidationError("document_type is required.")
    return document_type.strip()


def _validate_assignment_consistency(
    assignment: DocumentSignatureAssignment,
) -> None:
    school_id = assignment.school_id

    for field_name in ("signatory", "signature", "stamp"):
        related = getattr(assignment, field_name, None)
        if related is None:
            continue

        related_school_id = getattr(related, "school_id", None)
        if (
            related_school_id is not None
            and related_school_id != school_id
        ):
            raise ValidationError(
                f"{field_name} belongs to another school."
            )

    if (
        assignment.valid_from
        and assignment.valid_until
        and assignment.valid_until < assignment.valid_from
    ):
        raise ValidationError(
            "Assignment valid_until cannot be earlier than valid_from."
        )


def _resource_is_usable(resource: Any, today: date) -> bool:
    return bool(
        resource
        and getattr(resource, "is_active", False)
        and _is_within_validity(resource, today)
    )


def resolve_assignment(
    school: Any,
    document_type: str,
    *,
    on_date: date | None = None,
) -> DocumentSignatureAssignment | None:
    """
    Return the valid active assignment for a school and document type.

    Invalid or expired resources are excluded. An expired/disabled stamp does
    not invalidate an otherwise valid signature assignment; it is omitted
    from rendering instead.
    """
    _validate_school(school)
    document_type = _validate_document_type(document_type)
    current_date = on_date or _today()

    assignments = (
        DocumentSignatureAssignment.objects
        .select_related("signatory", "signature", "stamp")
        .filter(
            school=school,
            document_type=document_type,
            is_active=True,
        )
        .order_by("-valid_from", "-pk")
    )

    for assignment in assignments:
        if not _is_within_validity(assignment, current_date):
            continue

        _validate_assignment_consistency(assignment)

        if not _resource_is_usable(
            assignment.signatory,
            current_date,
        ):
            continue

        signature = assignment.signature
        fallback_signature = getattr(
            assignment.signatory,
            "signature_image",
            None,
        )

        if signature is not None and not _resource_is_usable(
            signature,
            current_date,
        ):
            signature = None

        if signature is None and not fallback_signature:
            continue

        stamp = assignment.stamp
        if stamp is not None and not _resource_is_usable(
            stamp,
            current_date,
        ):
            stamp = None

        # These are transient rendering substitutions only; they are not saved.
        assignment.signature = signature
        assignment.stamp = stamp
        return assignment

    return None


def build_signature_context(
    school: Any,
    document_type: str,
    *,
    on_date: date | None = None,
) -> dict[str, Any]:
    """
    Return a template-ready signature context or an empty mapping.

    Internal identifier keys allow generated documents to freeze exactly which
    resources were used without exposing that metadata in public templates.
    """
    assignment = resolve_assignment(
        school,
        document_type,
        on_date=on_date,
    )
    if assignment is None:
        return {}

    signatory = assignment.signatory
    signature_image = None

    if assignment.signature is not None:
        signature_image = assignment.signature.image
    else:
        signature_image = getattr(
            signatory,
            "signature_image",
            None,
        )

    stamp_image = (
        assignment.stamp.image
        if assignment.stamp is not None
        else None
    )

    return {
        "signatory_name": getattr(
            signatory,
            "full_name",
            str(signatory),
        ),
        "signatory_title": getattr(signatory, "title", ""),
        "signature_image": signature_image,
        "stamp_image": stamp_image,
        "position": assignment.position,
        "_assignment_id": assignment.pk,
        "_signatory_id": assignment.signatory_id,
        "_signature_id": (
            assignment.signature_id
            if assignment.signature is not None
            else None
        ),
        "_stamp_id": (
            assignment.stamp_id
            if assignment.stamp is not None
            else None
        ),
    }


def _snapshot(
    assignment: DocumentSignatureAssignment,
) -> dict[str, Any]:
    return {
        "assignment_id": assignment.pk,
        "school_id": assignment.school_id,
        "document_type": assignment.document_type,
        "signatory_id": assignment.signatory_id,
        "signature_id": assignment.signature_id,
        "stamp_id": assignment.stamp_id,
        "position": assignment.position,
        "is_active": assignment.is_active,
        "valid_from": (
            assignment.valid_from.isoformat()
            if assignment.valid_from
            else None
        ),
        "valid_until": (
            assignment.valid_until.isoformat()
            if assignment.valid_until
            else None
        ),
    }


def _validate_changed_by(
    *,
    changed_by: Any,
    school_id: Any,
) -> None:
    if getattr(changed_by, "pk", None) is None:
        raise ValidationError("changed_by must be a persisted user.")

    if hasattr(changed_by, "is_active") and not changed_by.is_active:
        raise ValidationError(
            "Inactive users cannot update signature assignments."
        )

    changed_by_school_id = getattr(changed_by, "school_id", None)
    if (
        changed_by_school_id is not None
        and changed_by_school_id != school_id
        and not getattr(changed_by, "is_superuser", False)
    ):
        raise ValidationError(
            "changed_by belongs to another school."
        )


@transaction.atomic
def update_assignment(
    *,
    assignment: DocumentSignatureAssignment,
    changed_by: Any,
    **new_values: Any,
) -> DocumentSignatureAssignment:
    """
    Update a signature assignment and write an immutable before/after history.

    Unknown fields are rejected. The row is locked to prevent concurrent
    updates from producing misleading audit history.
    """
    if getattr(assignment, "pk", None) is None:
        raise ValidationError(
            "A persisted signature assignment is required."
        )

    unknown_fields = set(new_values) - _ALLOWED_UPDATE_FIELDS
    if unknown_fields:
        raise ValidationError(
            "Unsupported assignment fields: "
            + ", ".join(sorted(unknown_fields))
        )

    if not new_values:
        raise ValidationError(
            "At least one assignment field must be supplied."
        )

    locked = (
        DocumentSignatureAssignment.objects
        .select_for_update()
        .select_related("school", "signatory", "signature", "stamp")
        .get(pk=assignment.pk)
    )

    _validate_changed_by(
        changed_by=changed_by,
        school_id=locked.school_id,
    )

    old_snapshot = _snapshot(locked)

    for field_name, value in new_values.items():
        setattr(locked, field_name, value)

    _validate_assignment_consistency(locked)
    locked.full_clean()
    locked.save(update_fields=list(new_values.keys()))

    new_snapshot = _snapshot(locked)

    SignatureAssignmentHistory.objects.create(
        school=locked.school,
        document_type=locked.document_type,
        old_assignment=old_snapshot,
        new_assignment=new_snapshot,
        changed_by=changed_by,
    )

    logger.info(
        "Updated signature assignment %s for school %s and document %s.",
        locked.pk,
        locked.school_id,
        locked.document_type,
    )
    return locked


@transaction.atomic
def deactivate_assignment(
    *,
    assignment: DocumentSignatureAssignment,
    changed_by: Any,
) -> DocumentSignatureAssignment:
    """
    Convenience wrapper that preserves the same audited update pathway.
    """
    return update_assignment(
        assignment=assignment,
        changed_by=changed_by,
        is_active=False,
    )