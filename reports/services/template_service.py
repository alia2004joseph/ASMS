"""
Production service for resolving, versioning, and previewing report templates.

Security boundary
-----------------
Callers must pass a school resolved from the authenticated request context.
This service never accepts a client-supplied school identifier.

Responsibilities
----------------
- resolve the active school template with a system-default fallback;
- create immutable template versions under row locking;
- enforce one active version per template scope;
- validate school and user consistency;
- render sanitized previews through the production template path.

The service does not persist preview data and must never be called with live
student or guardian records.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Mapping
from typing import Any

from django.db import transaction
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from reports.exceptions import ValidationError
from reports.models.report_definitions import ReportTemplate


logger = logging.getLogger(__name__)

MAX_DOCUMENT_TYPE_LENGTH = 100
MAX_TEMPLATE_VERSION_RETRIES = 3

_ALLOWED_VERSION_FIELDS = {
    "branding",
    "page_config",
    "placement_config",
    "grading_display_format",
    "layout_config",
    "template_engine",
    "report_type",
    "is_default",
}

_SAFE_DOCUMENT_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_school(school: Any) -> None:
    if getattr(school, "pk", None) is None:
        raise ValidationError("A persisted school is required.")


def _normalise_document_type(document_type: str) -> str:
    if not isinstance(document_type, str) or not document_type.strip():
        raise ValidationError("document_type is required.")

    value = document_type.strip()

    if len(value) > MAX_DOCUMENT_TYPE_LENGTH:
        raise ValidationError(
            f"document_type may not exceed "
            f"{MAX_DOCUMENT_TYPE_LENGTH} characters."
        )

    if not _SAFE_DOCUMENT_TYPE_PATTERN.fullmatch(value):
        raise ValidationError(
            "document_type contains unsupported characters."
        )

    return value


def _validate_actor(
    *,
    user: Any,
    school_id: Any | None,
) -> None:
    if getattr(user, "pk", None) is None:
        raise ValidationError("updated_by must be a persisted user.")

    if hasattr(user, "is_active") and not user.is_active:
        raise ValidationError(
            "Inactive users cannot manage report templates."
        )

    user_school_id = getattr(user, "school_id", None)
    if (
        school_id is not None
        and user_school_id is not None
        and user_school_id != school_id
        and not getattr(user, "is_superuser", False)
    ):
        raise ValidationError(
            "updated_by belongs to another school."
        )


def _as_mapping(
    value: Any,
    *,
    field_name: str,
) -> dict[str, Any]:
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise ValidationError(
            f"{field_name} must be an object."
        )

    return copy.deepcopy(dict(value))


def _merge_mapping(
    current: Any,
    update: Any,
    *,
    field_name: str,
) -> dict[str, Any]:
    base = _as_mapping(current, field_name=field_name)
    patch = _as_mapping(update, field_name=field_name)
    return {**base, **patch}


def resolve_active_template(
    school: Any,
    document_type: str,
) -> ReportTemplate | None:
    """
    Resolve the active template for one school and document type.

    Resolution order:
    1. newest active school-specific template;
    2. newest active system-default template;
    3. ``None``.

    A system default must not be tied to another school.
    """
    _validate_school(school)
    document_type = _normalise_document_type(document_type)

    school_template = (
        ReportTemplate.objects
        .filter(
            school=school,
            document_type=document_type,
            is_active=True,
        )
        .order_by("-version", "-pk")
        .first()
    )
    if school_template is not None:
        return school_template

    system_query = ReportTemplate.objects.filter(
        document_type=document_type,
        is_active=True,
        is_system_default=True,
    )

    # System defaults should be global. Retaining NULL-school filtering avoids
    # a misconfigured school-owned record leaking across tenants.
    if any(
        field.name == "school"
        for field in ReportTemplate._meta.get_fields()
    ):
        system_query = system_query.filter(school__isnull=True)

    return system_query.order_by("-version", "-pk").first()


def _build_new_version(
    *,
    previous: ReportTemplate,
    updated_fields: Mapping[str, Any],
    updated_by: Any,
    version: int,
) -> ReportTemplate:
    new_template = ReportTemplate(
        school=previous.school,
        report_type=updated_fields.get(
            "report_type",
            previous.report_type,
        ),
        document_type=previous.document_type,
        template_engine=updated_fields.get(
            "template_engine",
            previous.template_engine,
        ),
        branding=_merge_mapping(
            previous.branding,
            updated_fields.get("branding"),
            field_name="branding",
        ),
        page_config=_merge_mapping(
            previous.page_config,
            updated_fields.get("page_config"),
            field_name="page_config",
        ),
        placement_config=_merge_mapping(
            previous.placement_config,
            updated_fields.get("placement_config"),
            field_name="placement_config",
        ),
        grading_display_format=updated_fields.get(
            "grading_display_format",
            previous.grading_display_format,
        ),
        layout_config=_merge_mapping(
            previous.layout_config,
            updated_fields.get("layout_config"),
            field_name="layout_config",
        ),
        version=version,
        is_active=True,
        is_default=updated_fields.get(
            "is_default",
            previous.is_default,
        ),
        created_by=updated_by,
    )

    if hasattr(new_template, "is_system_default"):
        new_template.is_system_default = getattr(
            previous,
            "is_system_default",
            False,
        )

    new_template.full_clean()
    new_template.save()
    return new_template


@transaction.atomic
def create_new_template_version(
    *,
    previous: ReportTemplate,
    updated_fields: dict[str, Any],
    updated_by: Any,
) -> ReportTemplate:
    """
    Create the next immutable template version.

    The previous row is locked and deactivated in the same transaction.
    Unknown fields are rejected to prevent accidental model mutation.
    """
    if getattr(previous, "pk", None) is None:
        raise ValidationError(
            "A persisted previous template is required."
        )

    if not isinstance(updated_fields, Mapping):
        raise ValidationError(
            "updated_fields must be an object."
        )

    unknown_fields = set(updated_fields) - _ALLOWED_VERSION_FIELDS
    if unknown_fields:
        raise ValidationError(
            "Unsupported template fields: "
            + ", ".join(sorted(unknown_fields))
        )

    locked = (
        ReportTemplate.objects
        .select_for_update()
        .select_related("school", "created_by")
        .get(pk=previous.pk)
    )

    _validate_actor(
        user=updated_by,
        school_id=locked.school_id,
    )

    if not locked.is_active:
        raise ValidationError(
            "Only the active template version can be superseded."
        )

    scope_filter = {
        "school_id": locked.school_id,
        "document_type": locked.document_type,
    }

    active_versions = (
        ReportTemplate.objects
        .select_for_update()
        .filter(**scope_filter, is_active=True)
    )

    if active_versions.exclude(pk=locked.pk).exists():
        raise ValidationError(
            "Multiple active templates exist for this scope. "
            "Resolve the data integrity issue before versioning."
        )

    latest_version = (
        ReportTemplate.objects
        .filter(**scope_filter)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    next_version = int(latest_version or 0) + 1

    new_template = _build_new_version(
        previous=locked,
        updated_fields=updated_fields,
        updated_by=updated_by,
        version=next_version,
    )

    locked.is_active = False
    locked.full_clean()
    locked.save(update_fields=["is_active"])

    logger.info(
        "Created report template version %s from template %s "
        "for school %s and document type %s.",
        new_template.pk,
        locked.pk,
        locked.school_id,
        locked.document_type,
    )
    return new_template


def _template_path(template: ReportTemplate) -> str:
    document_type = _normalise_document_type(
        template.document_type,
    )
    return (
        f"reports/{document_type.lower()}/document.html"
    )


def _sanitize_preview_context(
    sample_context: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(sample_context, Mapping):
        raise ValidationError(
            "sample_context must be an object."
        )

    # Defensive deep copy prevents templates or callers from mutating the
    # original sample payload after validation.
    return copy.deepcopy(dict(sample_context))


def render_preview(
    template: ReportTemplate,
    sample_context: dict[str, Any],
) -> str:
    """
    Render a preview through the same template used in production.

    The caller is responsible for supplying synthetic/sample-only data.
    """
    if getattr(template, "pk", None) is None:
        raise ValidationError(
            "A persisted report template is required."
        )

    if not template.is_active:
        raise ValidationError(
            "Only an active report template can be previewed."
        )

    preview_data = _sanitize_preview_context(sample_context)

    reserved_keys = {
        "branding",
        "page_config",
        "placement_config",
        "grading_display_format",
        "layout_config",
        "report_template",
        "is_preview",
    }
    conflicting_keys = reserved_keys.intersection(preview_data)
    if conflicting_keys:
        raise ValidationError(
            "sample_context contains reserved keys: "
            + ", ".join(sorted(conflicting_keys))
        )

    context = {
        **preview_data,
        "branding": copy.deepcopy(template.branding or {}),
        "page_config": copy.deepcopy(
            template.page_config or {},
        ),
        "placement_config": copy.deepcopy(
            template.placement_config or {},
        ),
        "grading_display_format": (
            template.grading_display_format
        ),
        "layout_config": copy.deepcopy(
            template.layout_config or {},
        ),
        "report_template": template,
        "is_preview": True,
    }

    path = _template_path(template)

    try:
        return render_to_string(path, context)
    except TemplateDoesNotExist as exc:
        logger.exception(
            "Report preview template does not exist: %s.",
            path,
        )
        raise ValidationError(
            "The configured report template file does not exist."
        ) from exc
    except Exception:
        logger.exception(
            "Failed to render preview for report template %s.",
            template.pk,
        )
        raise