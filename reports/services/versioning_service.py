"""
Production version-chain management service.

All versioned Reports models MUST create, supersede, revoke and query
versions exclusively through this service.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from reports.exceptions import ValidationError

logger = logging.getLogger(__name__)


def _validate_instance(instance: Any):
    if getattr(instance, "pk", None) is None:
        raise ValidationError("A persisted versioned instance is required.")
    required = (
        "root_id","version","is_latest","is_revoked",
        "previous_version","regeneration_reason",
        "revoked_reason","revoked_at","revoked_by",
    )
    for f in required:
        if not hasattr(instance, f):
            raise ValidationError(f"Missing VersionedModel field '{f}'.")


def _validate_actor(user: Any, school_id: Any):
    if getattr(user, "pk", None) is None:
        raise ValidationError("A persisted user is required.")
    if hasattr(user, "is_active") and not user.is_active:
        raise ValidationError("Inactive users cannot modify versions.")
    us = getattr(user, "school_id", None)
    if us is not None and school_id is not None and us != school_id and not getattr(user,"is_superuser",False):
        raise ValidationError("User belongs to another school.")


@transaction.atomic
def create_new_version(*, previous_instance, reason:str, generated_by, extra_fields:dict|None=None):
    _validate_instance(previous_instance)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("regeneration_reason is required.")

    model = previous_instance.__class__
    previous = (
        model.objects.select_for_update()
        .get(pk=previous_instance.pk)
    )

    if previous.is_revoked:
        raise ValidationError("A revoked document cannot be versioned.")
    if not previous.is_latest:
        raise ValidationError("Only the latest version can be superseded.")

    _validate_actor(generated_by, getattr(previous,"school_id",None))

    if model.objects.select_for_update().filter(
        root_id=previous.root_id, is_latest=True
    ).exclude(pk=previous.pk).exists():
        raise ValidationError("Multiple latest versions detected.")

    new = model.objects.get(pk=previous.pk)
    new.pk = None
    if hasattr(new,"id"):
        new.id = None

    new.root_id = previous.root_id
    new.version = previous.version + 1
    new.previous_version = previous
    new.is_latest = True
    new.is_revoked = False
    new.regeneration_reason = reason
    new.revoked_reason = ""
    new.revoked_at = None
    new.revoked_by = None

    if hasattr(new,"generated_by"):
        new.generated_by = generated_by

    for k,v in (extra_fields or {}).items():
        setattr(new,k,v)

    new.full_clean()
    new.save()

    previous.is_latest = False
    previous.full_clean()
    previous.save(update_fields=["is_latest"])

    logger.info(
        "Created version %s from %s for root %s.",
        new.version, previous.version, previous.root_id
    )
    return new


@transaction.atomic
def revoke(*, instance, reason:str, revoked_by):
    _validate_instance(instance)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("revoked_reason is required.")

    model = instance.__class__
    locked = model.objects.select_for_update().get(pk=instance.pk)

    if locked.is_revoked:
        raise ValidationError("Document is already revoked.")

    _validate_actor(revoked_by, getattr(locked,"school_id",None))

    locked.is_revoked = True
    locked.revoked_reason = reason
    locked.revoked_at = timezone.now()
    locked.revoked_by = revoked_by
    locked.full_clean()
    locked.save(update_fields=[
        "is_revoked","revoked_reason","revoked_at","revoked_by"
    ])

    logger.warning("Revoked document %s.", locked.pk)
    return locked


def get_version_chain(model_cls, root_id):
    if root_id in (None,""):
        raise ValidationError("root_id is required.")
    return (
        model_cls.objects.filter(root_id=root_id)
        .order_by("version","pk")
    )


def get_latest(model_cls, root_id):
    if root_id in (None,""):
        raise ValidationError("root_id is required.")
    return (
        model_cls.objects.filter(
            root_id=root_id,
            is_latest=True,
        ).first()
    )