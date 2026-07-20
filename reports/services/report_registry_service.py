"""
Authoritative service boundary for reportable source and field access.

Only this module and ``reports.registry.reportable_fields`` should know how
an authenticated Accounts user is translated into a report-role identifier.
Serializers, services, ViewSets, and Celery tasks should call these helpers
instead of importing the registry directly.

The registry remains the source of truth for:
- registered report sources;
- registered reportable fields;
- per-role source access;
- per-role field access.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from reports.exceptions import ValidationError
from reports.registry import reportable_fields as registry


SUPERUSER_ROLE = "SUPERUSER"
DEFAULT_ROLE_ATTRIBUTE = "role"
ROLE_ATTRIBUTE_SETTING = "REPORTS_USER_ROLE_ATTRIBUTE"


def _normalise_key(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} is required.")
    return value.strip()


def _normalise_role(value: Any) -> str:
    if value is None:
        return ""

    if hasattr(value, "value"):
        value = value.value

    role = str(value).strip().upper()
    return role


def _role_attribute_name() -> str:
    attribute_name = getattr(
        settings,
        ROLE_ATTRIBUTE_SETTING,
        DEFAULT_ROLE_ATTRIBUTE,
    )

    if not isinstance(attribute_name, str) or not attribute_name.strip():
        raise ImproperlyConfigured(
            f"{ROLE_ATTRIBUTE_SETTING} must be a non-empty attribute name."
        )

    return attribute_name.strip()


def _read_nested_attribute(instance: Any, path: str) -> Any:
    current = instance

    for segment in path.split("."):
        if current is None:
            return None

        if not segment or segment.startswith("_"):
            raise ImproperlyConfigured(
                f"{ROLE_ATTRIBUTE_SETTING} contains an invalid attribute path."
            )

        current = getattr(current, segment, None)

        if callable(current):
            current = current()

    return current


def get_role_for_user(user: Any) -> str:
    """
    Resolve the canonical Reports role for an Accounts user.

    Superusers always receive ``SUPERUSER``. For ordinary users, the role is
    read from ``settings.REPORTS_USER_ROLE_ATTRIBUTE`` (default: ``role``).
    Nested paths such as ``profile.role`` are supported.
    """
    if user is None:
        return ""

    if getattr(user, "is_superuser", False):
        return SUPERUSER_ROLE

    if hasattr(user, "is_authenticated") and not user.is_authenticated:
        return ""

    raw_role = _read_nested_attribute(
        user,
        _role_attribute_name(),
    )
    return _normalise_role(raw_role)


def _allowed_roles(resource: Any) -> set[str]:
    roles = getattr(resource, "allowed_roles", None)
    if roles is None:
        return set()

    if isinstance(roles, str):
        roles = [roles]

    if not isinstance(roles, Iterable):
        raise ImproperlyConfigured(
            "Registry resource allowed_roles must be iterable."
        )

    return {
        normalised
        for role in roles
        if (normalised := _normalise_role(role))
    }


def _role_has_access(resource: Any, role: str) -> bool:
    if not role:
        return False
    if role == SUPERUSER_ROLE:
        return True
    return role in _allowed_roles(resource)


def get_available_sources(user: Any):
    """
    Return sources visible to the user.

    Registry-level filtering is retained, while superusers receive every
    registered source through the registry's canonical listing function.
    """
    role = get_role_for_user(user)
    if not role:
        return []

    return registry.get_sources_for_role(role)


def get_available_fields(source_key: str, user: Any):
    """
    Return fields visible to the user for one accessible source.

    An inaccessible source always returns an empty collection rather than
    leaking its field definitions.
    """
    source_key = _normalise_key(
        source_key,
        field_name="source_key",
    )

    if validate_source_access(source_key, user) is None:
        return []

    role = get_role_for_user(user)
    return registry.get_fields_for_role(source_key, role)


def validate_source_access(source_key: str, user: Any):
    """
    Return the source definition when access is allowed, otherwise ``None``.
    """
    source_key = _normalise_key(
        source_key,
        field_name="source_key",
    )
    role = get_role_for_user(user)

    if not role:
        return None

    source = registry.get_source(source_key)
    if source is None:
        return None

    if not _role_has_access(source, role):
        return None

    return source


def validate_field_access(
    source_key: str,
    field_key: str,
    user: Any,
):
    """
    Return the reportable field when access is allowed, otherwise ``None``.

    Source access is checked first to avoid exposing registered field names
    from a source the user cannot access.
    """
    source_key = _normalise_key(
        source_key,
        field_name="source_key",
    )
    field_key = _normalise_key(
        field_key,
        field_name="field_key",
    )

    if validate_source_access(source_key, user) is None:
        return None

    role = get_role_for_user(user)
    return registry.resolve_field(
        source_key,
        field_key,
        role,
    )


def require_source_access(source_key: str, user: Any):
    """
    Return an accessible source or raise a domain validation error.
    """
    source = validate_source_access(source_key, user)
    if source is None:
        raise ValidationError(
            "The requested report source does not exist or is not accessible."
        )
    return source


def require_field_access(
    source_key: str,
    field_key: str,
    user: Any,
):
    """
    Return an accessible field or raise a domain validation error.
    """
    field = validate_field_access(
        source_key,
        field_key,
        user,
    )
    if field is None:
        raise ValidationError(
            "The requested report field does not exist or is not accessible."
        )
    return field


def require_fields_access(
    source_key: str,
    field_keys: Iterable[str],
    user: Any,
) -> list[Any]:
    """
    Validate a collection of fields while preserving caller order.

    Duplicate field keys are rejected because they create ambiguous exports,
    aliases, sorting, and aggregation behavior.
    """
    source_key = _normalise_key(
        source_key,
        field_name="source_key",
    )

    if isinstance(field_keys, str) or not isinstance(field_keys, Iterable):
        raise ValidationError("field_keys must be an iterable of field names.")

    resolved_fields: list[Any] = []
    seen: set[str] = set()

    for raw_field_key in field_keys:
        field_key = _normalise_key(
            raw_field_key,
            field_name="field_key",
        )

        if field_key in seen:
            raise ValidationError(
                f"Duplicate report field '{field_key}'."
            )
        seen.add(field_key)

        resolved_fields.append(
            require_field_access(
                source_key,
                field_key,
                user,
            )
        )

    if not resolved_fields:
        raise ValidationError(
            "At least one report field is required."
        )

    return resolved_fields