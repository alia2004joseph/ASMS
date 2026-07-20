"""
Stable integration boundary between Reports and the Finance application.

The Reports module must never depend directly on Finance internals. This
adapter resolves one configured Finance balance-summary provider, calls it,
and normalises the response into a strict contract used by report services.

Configuration
-------------
Set the following Django setting to the dotted path of the real Finance
provider:

    REPORTS_FINANCE_BALANCE_PROVIDER = (
        "finance.services.payment_service.PaymentService.get_balance_summary"
    )

The configured callable must accept keyword arguments ``student`` and
``term`` and return either:

    {
        "invoiced_total": Decimal-compatible value,
        "paid_total": Decimal-compatible value,
        "outstanding_balance": Decimal-compatible value,
    }

or an object exposing attributes with the same names.

All money values are returned as finite ``Decimal`` instances. Reports never
recompute invoice, payment, allocation, waiver, credit, or balance logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from reports.exceptions import ValidationError


DEFAULT_PROVIDER_SETTING = "REPORTS_FINANCE_BALANCE_PROVIDER"

_REQUIRED_KEYS = (
    "invoiced_total",
    "paid_total",
    "outstanding_balance",
)


@dataclass(frozen=True, slots=True)
class StudentBalanceSummary:
    invoiced_total: Decimal
    paid_total: Decimal
    outstanding_balance: Decimal

    def as_dict(self) -> dict[str, Decimal]:
        return {
            "invoiced_total": self.invoiced_total,
            "paid_total": self.paid_total,
            "outstanding_balance": self.outstanding_balance,
        }


def _get_provider_path() -> str:
    provider_path = getattr(settings, DEFAULT_PROVIDER_SETTING, "")

    if not isinstance(provider_path, str) or not provider_path.strip():
        raise ImproperlyConfigured(
            f"{DEFAULT_PROVIDER_SETTING} must be configured with the dotted "
            "path of the Finance balance-summary callable."
        )

    return provider_path.strip()


def _load_provider() -> Callable[..., Any]:
    provider_path = _get_provider_path()

    try:
        provider = import_string(provider_path)
    except (ImportError, AttributeError) as exc:
        raise ImproperlyConfigured(
            f"Could not import Finance balance provider "
            f"{provider_path!r}."
        ) from exc

    if not callable(provider):
        raise ImproperlyConfigured(
            f"Configured Finance balance provider {provider_path!r} "
            "is not callable."
        )

    return provider


def _extract_value(raw_summary: Any, key: str) -> Any:
    if isinstance(raw_summary, Mapping):
        if key not in raw_summary:
            raise ValidationError(
                f"Finance balance summary is missing required key '{key}'."
            )
        return raw_summary[key]

    if hasattr(raw_summary, key):
        return getattr(raw_summary, key)

    raise ValidationError(
        f"Finance balance summary is missing required value '{key}'."
    )


def _to_money(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValidationError(
            f"Finance balance value '{field_name}' must be numeric."
        )

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            f"Finance balance value '{field_name}' is invalid."
        ) from exc

    if not amount.is_finite():
        raise ValidationError(
            f"Finance balance value '{field_name}' must be finite."
        )

    return amount


def _normalise_summary(raw_summary: Any) -> StudentBalanceSummary:
    if raw_summary is None:
        raise ValidationError(
            "Finance balance provider returned no summary."
        )

    values = {
        key: _to_money(
            _extract_value(raw_summary, key),
            field_name=key,
        )
        for key in _REQUIRED_KEYS
    }

    if values["invoiced_total"] < Decimal("0.00"):
        raise ValidationError(
            "Finance invoiced_total cannot be negative."
        )

    if values["paid_total"] < Decimal("0.00"):
        raise ValidationError(
            "Finance paid_total cannot be negative."
        )

    return StudentBalanceSummary(**values)


def get_student_balance_summary(
    student: Any,
    term: Any,
) -> dict[str, Decimal]:
    """
    Return the canonical Reports balance-summary contract.

    Finance remains the source of truth. This function performs only:
    - provider discovery;
    - integration validation;
    - Decimal normalisation;
    - stable contract shaping.

    It deliberately does not derive outstanding balances from invoiced and
    paid totals because doing so would duplicate Finance business logic and
    could ignore allocations, waivers, credits, penalties, refunds, or other
    Finance rules.
    """
    if getattr(student, "pk", None) is None:
        raise ValidationError(
            "A persisted student is required for a balance summary."
        )

    if getattr(term, "pk", None) is None:
        raise ValidationError(
            "A persisted academic term is required for a balance summary."
        )

    student_school_id = getattr(student, "school_id", None)
    term_school_id = getattr(term, "school_id", None)

    if (
        student_school_id is not None
        and term_school_id is not None
        and student_school_id != term_school_id
    ):
        raise ValidationError(
            "Student and academic term must belong to the same school."
        )

    provider = _load_provider()

    try:
        raw_summary = provider(student=student, term=term)
    except TypeError as exc:
        raise ImproperlyConfigured(
            "The configured Finance balance provider must accept keyword "
            "arguments 'student' and 'term'."
        ) from exc

    return _normalise_summary(raw_summary).as_dict()