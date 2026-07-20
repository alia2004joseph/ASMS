"""
Performance-history integration and snapshot service.

Live academic performance is always computed by the Academics/Grading
application. Reports consumes that result through one configured provider and
never reimplements grade, GPA, aggregate, ranking, or grading-policy logic.

Snapshots are written only when:
1. an official document freezes the current result; or
2. a scheduled analytics task captures trend data.

Configuration
-------------
Set this Django setting to the real Academics/Grading provider:

    REPORTS_PERFORMANCE_PROVIDER = (
        "academics.services.performance_service.get_student_performance"
    )

The provider must accept keyword arguments ``student`` and ``term`` and return
a mapping or object exposing the canonical fields documented by
``LivePerformance`` below.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from reports.constants import PerformanceSnapshotSource
from reports.exceptions import ValidationError
from reports.models.performance_history import PerformanceSnapshot


PERFORMANCE_PROVIDER_SETTING = "REPORTS_PERFORMANCE_PROVIDER"
MAX_SUBJECT_POSITIONS = 200
MAX_SUMMARY_LENGTH = 10_000


@dataclass(frozen=True, slots=True)
class LivePerformance:
    gpa: Decimal | None
    aggregate: Decimal | None
    class_position: int | None
    class_size: int | None
    subject_positions: dict[str, Any]
    class_average: Decimal | None
    school_average: Decimal | None
    performance_summary: str
    grading_policy_version: str
    computation_reference: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _provider_path() -> str:
    path = getattr(settings, PERFORMANCE_PROVIDER_SETTING, "")
    if not isinstance(path, str) or not path.strip():
        raise ImproperlyConfigured(
            f"{PERFORMANCE_PROVIDER_SETTING} must contain the dotted path "
            "of the Academics/Grading performance provider."
        )
    return path.strip()


def _load_provider() -> Callable[..., Any]:
    path = _provider_path()
    try:
        provider = import_string(path)
    except (ImportError, AttributeError) as exc:
        raise ImproperlyConfigured(
            f"Could not import performance provider {path!r}."
        ) from exc

    if not callable(provider):
        raise ImproperlyConfigured(
            f"Configured performance provider {path!r} is not callable."
        )
    return provider


def _extract(raw: Any, key: str, *, default: Any = None) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(key, default)
    return getattr(raw, key, default)


def _decimal_or_none(value: Any, *, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be numeric.")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} is not a valid number.") from exc

    if not result.is_finite():
        raise ValidationError(f"{field_name} must be finite.")
    if result < 0:
        raise ValidationError(f"{field_name} cannot be negative.")
    return result


def _positive_int_or_none(value: Any, *, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be an integer.")

    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be an integer.") from exc

    if result < 1:
        raise ValidationError(f"{field_name} must be at least 1.")
    return result


def _normalise_subject_positions(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise ValidationError("subject_positions must be an object.")
    if len(value) > MAX_SUBJECT_POSITIONS:
        raise ValidationError(
            f"subject_positions may contain at most "
            f"{MAX_SUBJECT_POSITIONS} subjects."
        )

    normalised: dict[str, Any] = {}
    for subject_key, raw_position in value.items():
        key = str(subject_key).strip()
        if not key:
            raise ValidationError(
                "subject_positions contains an empty subject key."
            )

        if isinstance(raw_position, Mapping):
            position = _positive_int_or_none(
                raw_position.get("position"),
                field_name=f"subject_positions[{key}].position",
            )
            class_size = _positive_int_or_none(
                raw_position.get("class_size"),
                field_name=f"subject_positions[{key}].class_size",
            )
            if (
                position is not None
                and class_size is not None
                and position > class_size
            ):
                raise ValidationError(
                    f"Subject position for '{key}' exceeds class size."
                )
            normalised[key] = {
                **dict(raw_position),
                "position": position,
                "class_size": class_size,
            }
        else:
            normalised[key] = _positive_int_or_none(
                raw_position,
                field_name=f"subject_positions[{key}]",
            )

    return normalised


def _normalise_live_performance(raw: Any) -> LivePerformance:
    if raw is None:
        raise ValidationError(
            "The Academics/Grading provider returned no performance data."
        )

    class_position = _positive_int_or_none(
        _extract(raw, "class_position"),
        field_name="class_position",
    )
    class_size = _positive_int_or_none(
        _extract(raw, "class_size"),
        field_name="class_size",
    )

    if (
        class_position is not None
        and class_size is not None
        and class_position > class_size
    ):
        raise ValidationError(
            "class_position cannot exceed class_size."
        )

    summary = str(_extract(raw, "performance_summary", "") or "").strip()
    if len(summary) > MAX_SUMMARY_LENGTH:
        raise ValidationError(
            f"performance_summary may not exceed "
            f"{MAX_SUMMARY_LENGTH} characters."
        )

    grading_policy_version = str(
        _extract(raw, "grading_policy_version", "") or ""
    ).strip()
    computation_reference = str(
        _extract(raw, "computation_reference", "") or ""
    ).strip()

    return LivePerformance(
        gpa=_decimal_or_none(_extract(raw, "gpa"), field_name="gpa"),
        aggregate=_decimal_or_none(
            _extract(raw, "aggregate"),
            field_name="aggregate",
        ),
        class_position=class_position,
        class_size=class_size,
        subject_positions=_normalise_subject_positions(
            _extract(raw, "subject_positions", {})
        ),
        class_average=_decimal_or_none(
            _extract(raw, "class_average"),
            field_name="class_average",
        ),
        school_average=_decimal_or_none(
            _extract(raw, "school_average"),
            field_name="school_average",
        ),
        performance_summary=summary,
        grading_policy_version=grading_policy_version,
        computation_reference=computation_reference,
    )


def _validate_context(*, student: Any, term: Any, school: Any | None = None) -> None:
    if getattr(student, "pk", None) is None:
        raise ValidationError("A persisted student is required.")
    if getattr(term, "pk", None) is None:
        raise ValidationError("A persisted academic term is required.")

    student_school_id = getattr(student, "school_id", None)
    term_school_id = getattr(term, "school_id", None)

    if (
        student_school_id is not None
        and term_school_id is not None
        and student_school_id != term_school_id
    ):
        raise ValidationError(
            "Student and academic term belong to different schools."
        )

    if school is not None:
        if getattr(school, "pk", None) is None:
            raise ValidationError("A persisted school is required.")
        if student_school_id is not None and student_school_id != school.pk:
            raise ValidationError("Student belongs to another school.")
        if term_school_id is not None and term_school_id != school.pk:
            raise ValidationError("Academic term belongs to another school.")


def _compute_live(student: Any, term: Any) -> dict[str, Any]:
    """
    Call the configured Academics/Grading provider and return validated data.

    No grade calculations are performed in Reports.
    """
    _validate_context(student=student, term=term)
    provider = _load_provider()

    try:
        raw = provider(student=student, term=term)
    except TypeError as exc:
        raise ImproperlyConfigured(
            "The configured performance provider must accept keyword "
            "arguments 'student' and 'term'."
        ) from exc

    return _normalise_live_performance(raw).as_dict()


def get_current_performance(
    student: Any,
    term: Any,
) -> dict[str, Any]:
    """Return validated, computed-on-read performance for one student."""
    return _compute_live(student, term)


@transaction.atomic
def freeze_snapshot(
    student: Any,
    term: Any,
    school: Any,
    *,
    snapshot_source: str = PerformanceSnapshotSource.OFFICAL_DOCUMENT,
    computed_by: Any | None = None,
) -> PerformanceSnapshot:
    """
    Freeze current performance idempotently for one source.

    The model's uniqueness constraint should cover
    ``(student, academic_term, snapshot_source)``. Existing snapshots are
    updated in place so retries from Celery or document issuance are safe.
    """
    _validate_context(student=student, term=term, school=school)

    if computed_by is not None:
        if getattr(computed_by, "pk", None) is None:
            raise ValidationError("computed_by must be a persisted user.")
        if hasattr(computed_by, "is_active") and not computed_by.is_active:
            raise ValidationError("Inactive users cannot freeze snapshots.")
        user_school_id = getattr(computed_by, "school_id", None)
        if (
            user_school_id is not None
            and user_school_id != school.pk
            and not getattr(computed_by, "is_superuser", False)
        ):
            raise ValidationError("computed_by belongs to another school.")

    data = _compute_live(student, term)
    now = timezone.now()

    lookup = {
        "student": student,
        "academic_term": term,
        "snapshot_source": snapshot_source,
    }
    defaults = {
        "school": school,
        "gpa": data["gpa"],
        "aggregate": data["aggregate"],
        "class_position": data["class_position"],
        "class_size": data["class_size"],
        "subject_positions": data["subject_positions"],
        "class_average": data["class_average"],
        "school_average": data["school_average"],
        "performance_summary": data["performance_summary"],
        "grading_policy_version": data["grading_policy_version"],
        "computed_by": computed_by,
        "computation_reference": data["computation_reference"],
        "computed_at": now,
    }

    try:
        snapshot = (
            PerformanceSnapshot.objects.select_for_update()
            .filter(**lookup)
            .first()
        )

        if snapshot is None:
            snapshot = PerformanceSnapshot(**lookup, **defaults)
        else:
            for field_name, value in defaults.items():
                setattr(snapshot, field_name, value)

        snapshot.full_clean()
        snapshot.save()
        return snapshot
    except IntegrityError:
        # Handles a concurrent first-write race while preserving idempotency.
        snapshot = (
            PerformanceSnapshot.objects.select_for_update()
            .get(**lookup)
        )
        for field_name, value in defaults.items():
            setattr(snapshot, field_name, value)
        snapshot.full_clean()
        snapshot.save()
        return snapshot


def get_history(
    student: Any,
    term_range: Iterable[Any] | None = None,
    *,
    snapshot_source: str | None = None,
) -> list[dict[str, Any]]:
    """Return chronological, chart-ready performance history."""
    if getattr(student, "pk", None) is None:
        raise ValidationError("A persisted student is required.")

    queryset = (
        PerformanceSnapshot.objects.filter(student=student)
        .select_related("academic_term")
        .order_by(
            "academic_term__start_date",
            "academic_term_id",
            "computed_at",
        )
    )

    if term_range is not None:
        term_ids = [
            getattr(term, "pk", term)
            for term in term_range
        ]
        term_ids = [term_id for term_id in term_ids if term_id is not None]
        if not term_ids:
            return []
        queryset = queryset.filter(academic_term_id__in=term_ids)

    if snapshot_source is not None:
        queryset = queryset.filter(snapshot_source=snapshot_source)

    return [
        {
            "term_id": snapshot.academic_term_id,
            "term_name": str(snapshot.academic_term),
            "snapshot_source": snapshot.snapshot_source,
            "computed_at": snapshot.computed_at,
            "gpa": snapshot.gpa,
            "aggregate": snapshot.aggregate,
            "class_position": snapshot.class_position,
            "class_size": snapshot.class_size,
            "class_average": snapshot.class_average,
            "school_average": snapshot.school_average,
        }
        for snapshot in queryset
    ]


def assess_academic_risk(
    student: Any,
    recent_terms: Sequence[Any],
    *,
    gpa_decline_threshold: Decimal | float | str = Decimal("0.30"),
    attendance_threshold_pct: Decimal | float | str = Decimal("80.00"),
    outstanding_balance_threshold: Decimal | float | str = Decimal("0.00"),
    attendance_summary: Mapping[str, Any] | None = None,
    finance_summary: Mapping[str, Any] | None = None,
    snapshot_source: str | None = None,
) -> dict[str, Any]:
    """
    Evaluate configurable academic-risk factors without storing a label.

    Attendance and Finance summaries are caller supplied so this function
    remains pure and does not couple Reports to those applications.
    """
    decline_threshold = _decimal_or_none(
        gpa_decline_threshold,
        field_name="gpa_decline_threshold",
    )
    attendance_threshold = _decimal_or_none(
        attendance_threshold_pct,
        field_name="attendance_threshold_pct",
    )
    balance_threshold = _decimal_or_none(
        outstanding_balance_threshold,
        field_name="outstanding_balance_threshold",
    )

    if decline_threshold is None:
        decline_threshold = Decimal("0.30")
    if attendance_threshold is None:
        attendance_threshold = Decimal("80.00")
    if balance_threshold is None:
        balance_threshold = Decimal("0.00")

    if attendance_threshold > Decimal("100.00"):
        raise ValidationError(
            "attendance_threshold_pct cannot exceed 100."
        )

    history = get_history(
        student,
        term_range=recent_terms,
        snapshot_source=snapshot_source,
    )
    factors: list[str] = []
    details: dict[str, Any] = {}

    gpas = [
        Decimal(str(row["gpa"]))
        for row in history
        if row["gpa"] is not None
    ]
    if len(gpas) >= 2:
        decline = gpas[0] - gpas[-1]
        details["gpa_change"] = gpas[-1] - gpas[0]
        if decline >= decline_threshold:
            factors.append("gpa_decline")

    if attendance_summary is not None:
        attendance_pct = _decimal_or_none(
            attendance_summary.get("attendance_percentage"),
            field_name="attendance_percentage",
        )
        details["attendance_percentage"] = attendance_pct
        if (
            attendance_pct is not None
            and attendance_pct < attendance_threshold
        ):
            factors.append("low_attendance")

    if finance_summary is not None:
        outstanding = _decimal_or_none(
            finance_summary.get("outstanding_balance"),
            field_name="outstanding_balance",
        )
        details["outstanding_balance"] = outstanding
        if (
            outstanding is not None
            and outstanding > balance_threshold
        ):
            factors.append("outstanding_balance")

    return {
        "at_risk": bool(factors),
        "factors": factors,
        "details": details,
        "terms_evaluated": len(history),
    }