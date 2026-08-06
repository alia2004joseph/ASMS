"""
Production service for generating, regenerating, and verifying result slips.

The Reports application never recalculates marks, grades, GPA, aggregates,
positions, or pass/fail outcomes. Those values are supplied by the configured
Academics/Grading provider and frozen into the immutable result-slip version.

Configuration
-------------
Set the following Django setting to the dotted path of the real grading
provider:

    REPORTS_RESULT_SLIP_PROVIDER = (
        "academics.services.grading_service."
        "GradingService.get_term_subject_results"
    )

The provider must accept keyword arguments ``student`` and ``term`` and return
a mapping or object exposing:

    subjects
    aggregate_or_gpa
    class_average
    position
    pass_fail_status

Optional values such as ``class_size``, ``grading_policy_version``,
``computation_reference``, and ``remarks`` are preserved when supported by the
ResultSlip model.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from reports.constants import GeneratedReportStatus, VerificationResult
from reports.exceptions import ValidationError
from reports.models.result_slips import ResultSlip
from reports.services import performance_history_service, versioning_service
from reports.services.qrcode_service import generate_verification_code


logger = logging.getLogger(__name__)

RESULT_SLIP_PROVIDER_SETTING = "REPORTS_RESULT_SLIP_PROVIDER"
MAX_SUBJECTS = 100
MAX_TEXT_LENGTH = 2_000


@dataclass(frozen=True, slots=True)
class ResultSlipSnapshot:
    subjects: list[dict[str, Any]]
    aggregate_or_gpa: Decimal | None
    class_average: Decimal | None
    position: int | None
    class_size: int | None
    pass_fail_status: str
    remarks: str
    grading_policy_version: str
    computation_reference: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _provider_path() -> str:
    path = getattr(settings, RESULT_SLIP_PROVIDER_SETTING, "")
    if not isinstance(path, str) or not path.strip():
        raise ImproperlyConfigured(
            f"{RESULT_SLIP_PROVIDER_SETTING} must contain the dotted path "
            "of the Academics/Grading result provider."
        )
    return path.strip()


def _load_provider() -> Callable[..., Any]:
    path = _provider_path()

    try:
        provider = import_string(path)
    except (ImportError, AttributeError) as exc:
        raise ImproperlyConfigured(
            f"Could not import result-slip provider {path!r}."
        ) from exc

    if not callable(provider):
        raise ImproperlyConfigured(
            f"Configured result-slip provider {path!r} is not callable."
        )

    return provider


def _extract(raw: Any, key: str, default: Any = None) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(key, default)
    return getattr(raw, key, default)


def _decimal_or_none(value: Any, *, field_name: str) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be numeric.")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            f"{field_name} is not a valid number."
        ) from exc

    if not amount.is_finite():
        raise ValidationError(f"{field_name} must be finite.")

    return amount


def _positive_int_or_none(value: Any, *, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be an integer.")

    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{field_name} must be an integer."
        ) from exc

    if number < 1:
        raise ValidationError(
            f"{field_name} must be at least 1."
        )

    return number


def _bounded_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise ValidationError(
            f"{field_name} may not exceed {MAX_TEXT_LENGTH} characters."
        )
    return text


def _normalise_subject(subject: Any, index: int) -> dict[str, Any]:
    if isinstance(subject, Mapping):
        row = dict(subject)
    elif hasattr(subject, "__dict__"):
        row = {
            key: value
            for key, value in vars(subject).items()
            if not key.startswith("_")
        }
    else:
        raise ValidationError(
            f"subjects[{index}] must be an object."
        )

    if not row:
        raise ValidationError(
            f"subjects[{index}] cannot be empty."
        )

    return row


def _normalise_snapshot(raw: Any) -> ResultSlipSnapshot:
    if raw is None:
        raise ValidationError(
            "The Academics/Grading provider returned no result data."
        )

    raw_subjects = _extract(raw, "subjects", raw)

    if isinstance(raw_subjects, (str, bytes)) or not isinstance(
        raw_subjects,
        Sequence,
    ):
        raise ValidationError(
            "Result-slip subjects must be a sequence."
        )

    if len(raw_subjects) > MAX_SUBJECTS:
        raise ValidationError(
            f"A result slip may contain at most {MAX_SUBJECTS} subjects."
        )

    subjects = [
        _normalise_subject(subject, index)
        for index, subject in enumerate(raw_subjects)
    ]

    position = _positive_int_or_none(
        _extract(raw, "position"),
        field_name="position",
    )
    class_size = _positive_int_or_none(
        _extract(raw, "class_size"),
        field_name="class_size",
    )

    if (
        position is not None
        and class_size is not None
        and position > class_size
    ):
        raise ValidationError(
            "position cannot exceed class_size."
        )

    return ResultSlipSnapshot(
        subjects=subjects,
        aggregate_or_gpa=_decimal_or_none(
            _extract(raw, "aggregate_or_gpa"),
            field_name="aggregate_or_gpa",
        ),
        class_average=_decimal_or_none(
            _extract(raw, "class_average"),
            field_name="class_average",
        ),
        position=position,
        class_size=class_size,
        pass_fail_status=_bounded_text(
            _extract(raw, "pass_fail_status", ""),
            field_name="pass_fail_status",
        ),
        remarks=_bounded_text(
            _extract(raw, "remarks", ""),
            field_name="remarks",
        ),
        grading_policy_version=_bounded_text(
            _extract(raw, "grading_policy_version", ""),
            field_name="grading_policy_version",
        ),
        computation_reference=_bounded_text(
            _extract(raw, "computation_reference", ""),
            field_name="computation_reference",
        ),
    )


def _validate_context(
    *,
    student: Any,
    academic_year: Any,
    term: Any,
    class_ref: Any,
    school: Any,
    generated_by: Any | None = None,
) -> None:
    for name, instance in (
        ("student", student),
        ("academic_year", academic_year),
        ("term", term),
        ("class_ref", class_ref),
        ("school", school),
    ):
        if getattr(instance, "pk", None) is None:
            raise ValidationError(f"A persisted {name} is required.")

    for name, instance in (
        ("student", student),
        ("academic year", academic_year),
        ("term", term),
        ("class", class_ref),
    ):
        instance_school_id = getattr(instance, "school_id", None)
        if (
            instance_school_id is not None
            and instance_school_id != school.pk
        ):
            raise ValidationError(
                f"The {name} belongs to another school."
            )

    term_year_id = getattr(term, "academic_year_id", None)
    if (
        term_year_id is not None
        and term_year_id != academic_year.pk
    ):
        raise ValidationError(
            "The academic term does not belong to the academic year."
        )

    student_class_id = getattr(student, "classroom_id", None)
    if (
        student_class_id is not None
        and student_class_id != class_ref.pk
    ):
        raise ValidationError(
            "The student does not belong to the selected class."
        )

    if generated_by is not None:
        if getattr(generated_by, "pk", None) is None:
            raise ValidationError(
                "generated_by must be a persisted user."
            )
        if (
            hasattr(generated_by, "is_active")
            and not generated_by.is_active
        ):
            raise ValidationError(
                "Inactive users cannot generate result slips."
            )

        user_school_id = getattr(generated_by, "school_id", None)
        if (
            user_school_id is not None
            and user_school_id != school.pk
            and not getattr(generated_by, "is_superuser", False)
        ):
            raise ValidationError(
                "generated_by belongs to another school."
            )


def _fetch_subjects_snapshot(
    student: Any,
    term: Any,
) -> dict[str, Any]:
    """
    Fetch and validate a result snapshot from Academics/Grading.

    Reports performs no grade calculations.
    """
    provider = _load_provider()

    try:
        raw = provider(student=student, term=term)
    except TypeError as exc:
        raise ImproperlyConfigured(
            "The configured result-slip provider must accept keyword "
            "arguments 'student' and 'term'."
        ) from exc

    return _normalise_snapshot(raw).as_dict()


def _apply_optional_fields(
    instance: ResultSlip,
    snapshot: Mapping[str, Any],
) -> None:
    optional_fields = {
        "class_size": snapshot.get("class_size"),
        "remarks": snapshot.get("remarks", ""),
        "grading_policy_version": snapshot.get(
            "grading_policy_version",
            "",
        ),
        "computation_reference": snapshot.get(
            "computation_reference",
            "",
        ),
    }

    for field_name, value in optional_fields.items():
        if hasattr(instance, field_name):
            setattr(instance, field_name, value)


@transaction.atomic
def generate_result_slip(
    *,
    student: Any,
    academic_year: Any,
    term: Any,
    class_ref: Any,
    school: Any,
    show_position: bool = True,
    generated_by: Any | None = None,
) -> ResultSlip:
    _validate_context(
        student=student,
        academic_year=academic_year,
        term=term,
        class_ref=class_ref,
        school=school,
        generated_by=generated_by,
    )

    snapshot = _fetch_subjects_snapshot(student, term)

    slip = ResultSlip(
        school=school,
        student=student,
        academic_year=academic_year,
        term=term,
        classroom=class_ref,
        aggregate_or_gpa=snapshot["aggregate_or_gpa"],
        position=snapshot["position"] if show_position else None,
        class_average=snapshot["class_average"],
        pass_fail_status=snapshot["pass_fail_status"],
        verification_code=generate_verification_code(),
        status=GeneratedReportStatus.READY,
    )

    if hasattr(slip, "generated_by"):
        slip.generated_by = generated_by
    if hasattr(slip, "created_at"):
        slip.created_at = timezone.now()

    _apply_optional_fields(slip, snapshot)

    slip.full_clean()
    slip.save()

    performance_history_service.freeze_snapshot(
        student=student,
        term=term,
        school=school,
        computed_by=generated_by,
    )

    logger.info(
        "Generated result slip %s for student %s and term %s.",
        slip.pk,
        student.pk,
        term.pk,
    )
    return slip


@transaction.atomic
def regenerate_result_slip(
    *,
    previous: ResultSlip,
    reason: str,
    generated_by: Any,
) -> ResultSlip:
    if getattr(previous, "pk", None) is None:
        raise ValidationError(
            "A persisted result slip is required."
        )

    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError(
            "regeneration_reason is required."
        )

    previous = (
        ResultSlip.objects.select_for_update()
        .select_related(
            "student",
            "term",
            "academic_year",
            "classroom",
            "school",
        )
        .get(pk=previous.pk)
    )

    if previous.is_revoked:
        raise ValidationError(
            "A revoked result slip cannot be regenerated."
        )
    if not previous.is_latest:
        raise ValidationError(
            "Only the latest result-slip version can be regenerated."
        )

    _validate_context(
        student=previous.student,
        academic_year=previous.academic_year,
        term=previous.term,
        class_ref=previous.classroom,
        school=previous.school,
        generated_by=generated_by,
    )

    snapshot = _fetch_subjects_snapshot(
        previous.student,
        previous.term,
    )

    extra_fields = {
        "subjects_snapshot": snapshot["subjects"],
        "aggregate_or_gpa": snapshot["aggregate_or_gpa"],
        "position": (
            snapshot["position"]
            if previous.position is not None
            else None
        ),
        "class_average": snapshot["class_average"],
        "pass_fail_status": snapshot["pass_fail_status"],
        "verification_code": generate_verification_code(),
        "status": GeneratedReportStatus.READY,
    }

    for field_name in (
        "class_size",
        "remarks",
        "grading_policy_version",
        "computation_reference",
    ):
        if hasattr(previous, field_name):
            extra_fields[field_name] = snapshot.get(field_name)

    new_slip = versioning_service.create_new_version(
        previous_instance=previous,
        reason=reason,
        generated_by=generated_by,
        extra_fields=extra_fields,
    )

    performance_history_service.freeze_snapshot(
        student=previous.student,
        term=previous.term,
        school=previous.school,
        computed_by=generated_by,
    )

    logger.info(
        "Regenerated result slip %s from version %s.",
        new_slip.pk,
        previous.pk,
    )
    return new_slip


@transaction.atomic
def revoke_result_slip(
    *,
    slip: ResultSlip,
    reason: str,
    revoked_by: Any,
) -> ResultSlip:
    if getattr(slip, "pk", None) is None:
        raise ValidationError(
            "A persisted result slip is required."
        )

    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("revocation reason is required.")

    locked = (
        ResultSlip.objects.select_for_update()
        .get(pk=slip.pk)
    )

    if locked.is_revoked:
        raise ValidationError(
            "Result slip has already been revoked."
        )

    revoked = versioning_service.revoke(
        instance=locked,
        reason=reason,
        revoked_by=revoked_by,
    )

    logger.warning(
        "Revoked result slip %s.",
        locked.pk,
    )
    return revoked


def verify(verification_code: str) -> dict[str, Any]:
    """
    Public verification lookup with minimal personally identifiable data.
    """
    if (
        not isinstance(verification_code, str)
        or not verification_code.strip()
    ):
        return {"result": VerificationResult.NOT_FOUND}

    slip = (
        ResultSlip.objects
        .only(
            "id",
            "verification_code",
            "student_id",
            "term_id",
            "academic_year_id",
            "is_revoked",
            "is_latest",
        )
        .filter(
            verification_code=verification_code.strip(),
        )
        .first()
    )

    if slip is None:
        return {"result": VerificationResult.NOT_FOUND}

    if slip.is_revoked:
        return {"result": VerificationResult.REVOKED}

    if not slip.is_latest:
        return {"result": VerificationResult.SUPERSEDED}

    return {
        "result": VerificationResult.VALID,
        "result_slip_id": slip.pk,
        "term_id": slip.term_id,
        "academic_year_id": slip.academic_year_id,
    }