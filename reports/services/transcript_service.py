"""
Production transcript generation, versioning, and verification service.

The Reports application never calculates term GPA or cumulative GPA from raw
marks. The configured Academics/Grading provider is the sole authority for
all GPA values and credit totals.

Configuration
-------------
Configure a provider in Django settings:

    REPORTS_TRANSCRIPT_PROVIDER = (
        "academics.services.transcript_service."
        "TranscriptService.get_transcript_results"
    )

The provider must accept keyword arguments:

    student=<student instance>
    terms=<ordered tuple of term instances>

It must return an ordered iterable containing one result per requested term.
Each result may be a mapping or an object exposing:

    term
    term_gpa
    cumulative_gpa
    credits_earned

Optional fields are preserved when supported by TranscriptGPASnapshot:

    credits_attempted
    grade_points
    academic_standing
    grading_policy_version
    computation_reference

Reports freezes those authoritative values into TranscriptGPASnapshot rows.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
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
from reports.models.transcripts import (
    TranscriptGPASnapshot,
    TranscriptRecord,
)
from reports.services import versioning_service
from reports.services.qrcode_service import generate_verification_code


logger = logging.getLogger(__name__)

TRANSCRIPT_PROVIDER_SETTING = "REPORTS_TRANSCRIPT_PROVIDER"
MAX_TRANSCRIPT_TERMS = 100
MAX_TEXT_LENGTH = 2_000


@dataclass(frozen=True, slots=True)
class TermTranscriptResult:
    term: Any
    term_gpa: Decimal
    cumulative_gpa: Decimal
    credits_earned: Decimal
    credits_attempted: Decimal | None = None
    grade_points: Decimal | None = None
    academic_standing: str = ""
    grading_policy_version: str = ""
    computation_reference: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _provider_path() -> str:
    path = getattr(settings, TRANSCRIPT_PROVIDER_SETTING, "")
    if not isinstance(path, str) or not path.strip():
        raise ImproperlyConfigured(
            f"{TRANSCRIPT_PROVIDER_SETTING} must contain the dotted path "
            "of the Academics transcript provider."
        )
    return path.strip()


def _load_provider() -> Callable[..., Any]:
    path = _provider_path()

    try:
        provider = import_string(path)
    except (ImportError, AttributeError) as exc:
        raise ImproperlyConfigured(
            f"Could not import transcript provider {path!r}."
        ) from exc

    if not callable(provider):
        raise ImproperlyConfigured(
            f"Configured transcript provider {path!r} is not callable."
        )

    return provider


def _extract(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _decimal(
    value: Any,
    *,
    field_name: str,
    allow_none: bool = False,
    minimum: Decimal | None = Decimal("0"),
) -> Decimal | None:
    if value in (None, ""):
        if allow_none:
            return None
        raise ValidationError(f"{field_name} is required.")

    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be numeric.")

    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            f"{field_name} is not a valid decimal value."
        ) from exc

    if not number.is_finite():
        raise ValidationError(f"{field_name} must be finite.")

    if minimum is not None and number < minimum:
        raise ValidationError(
            f"{field_name} cannot be less than {minimum}."
        )

    return number


def _bounded_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise ValidationError(
            f"{field_name} may not exceed {MAX_TEXT_LENGTH} characters."
        )
    return text


def _normalise_terms(terms: Iterable[Any]) -> tuple[Any, ...]:
    if isinstance(terms, (str, bytes)) or not isinstance(
        terms,
        Iterable,
    ):
        raise ValidationError("terms must be an ordered iterable.")

    ordered_terms = tuple(terms)

    if not ordered_terms:
        raise ValidationError(
            "At least one academic term is required."
        )

    if len(ordered_terms) > MAX_TRANSCRIPT_TERMS:
        raise ValidationError(
            f"A transcript may contain at most "
            f"{MAX_TRANSCRIPT_TERMS} terms."
        )

    seen_ids: set[Any] = set()

    for term in ordered_terms:
        term_id = getattr(term, "pk", None)
        if term_id is None:
            raise ValidationError(
                "Every transcript term must be persisted."
            )
        if term_id in seen_ids:
            raise ValidationError(
                "Duplicate academic terms are not allowed."
            )
        seen_ids.add(term_id)

    return ordered_terms


def _validate_actor(
    *,
    actor: Any,
    school_id: Any,
    field_name: str,
) -> None:
    if getattr(actor, "pk", None) is None:
        raise ValidationError(
            f"{field_name} must be a persisted user."
        )

    if hasattr(actor, "is_active") and not actor.is_active:
        raise ValidationError(
            f"Inactive users cannot act as {field_name}."
        )

    actor_school_id = getattr(actor, "school_id", None)
    if (
        actor_school_id is not None
        and actor_school_id != school_id
        and not getattr(actor, "is_superuser", False)
    ):
        raise ValidationError(
            f"{field_name} belongs to another school."
        )


def _validate_context(
    *,
    student: Any,
    school: Any,
    terms: Sequence[Any],
    actor: Any,
    actor_field_name: str,
) -> None:
    if getattr(school, "pk", None) is None:
        raise ValidationError("A persisted school is required.")

    if getattr(student, "pk", None) is None:
        raise ValidationError("A persisted student is required.")

    student_school_id = getattr(student, "school_id", None)
    if (
        student_school_id is not None
        and student_school_id != school.pk
    ):
        raise ValidationError(
            "The student belongs to another school."
        )

    for term in terms:
        term_school_id = getattr(term, "school_id", None)
        if (
            term_school_id is not None
            and term_school_id != school.pk
        ):
            raise ValidationError(
                "A requested academic term belongs to another school."
            )

    _validate_actor(
        actor=actor,
        school_id=school.pk,
        field_name=actor_field_name,
    )


def _resolve_result_term(
    *,
    raw_result: Any,
    requested_term: Any,
) -> Any:
    result_term = _extract(raw_result, "term", requested_term)
    result_term_id = getattr(result_term, "pk", result_term)

    if result_term_id != requested_term.pk:
        raise ValidationError(
            "The transcript provider returned results in an unexpected "
            "term order or for the wrong term."
        )

    return requested_term


def _normalise_provider_results(
    raw_results: Any,
    requested_terms: Sequence[Any],
) -> list[TermTranscriptResult]:
    if isinstance(raw_results, Mapping):
        raw_results = raw_results.get(
            "terms",
            raw_results.get("results"),
        )

    if isinstance(raw_results, (str, bytes)) or not isinstance(
        raw_results,
        Sequence,
    ):
        raise ValidationError(
            "The transcript provider must return an ordered sequence."
        )

    if len(raw_results) != len(requested_terms):
        raise ValidationError(
            "The transcript provider must return exactly one result for "
            "each requested term."
        )

    normalised: list[TermTranscriptResult] = []

    for index, (raw_result, requested_term) in enumerate(
        zip(raw_results, requested_terms, strict=True)
    ):
        if not isinstance(raw_result, Mapping) and not hasattr(
            raw_result,
            "__dict__",
        ):
            raise ValidationError(
                f"Transcript result {index} must be an object."
            )

        normalised.append(
            TermTranscriptResult(
                term=_resolve_result_term(
                    raw_result=raw_result,
                    requested_term=requested_term,
                ),
                term_gpa=_decimal(
                    _extract(raw_result, "term_gpa"),
                    field_name=f"results[{index}].term_gpa",
                ),
                cumulative_gpa=_decimal(
                    _extract(raw_result, "cumulative_gpa"),
                    field_name=(
                        f"results[{index}].cumulative_gpa"
                    ),
                ),
                credits_earned=_decimal(
                    _extract(raw_result, "credits_earned"),
                    field_name=(
                        f"results[{index}].credits_earned"
                    ),
                ),
                credits_attempted=_decimal(
                    _extract(raw_result, "credits_attempted"),
                    field_name=(
                        f"results[{index}].credits_attempted"
                    ),
                    allow_none=True,
                ),
                grade_points=_decimal(
                    _extract(raw_result, "grade_points"),
                    field_name=(
                        f"results[{index}].grade_points"
                    ),
                    allow_none=True,
                ),
                academic_standing=_bounded_text(
                    _extract(raw_result, "academic_standing", ""),
                    field_name=(
                        f"results[{index}].academic_standing"
                    ),
                ),
                grading_policy_version=_bounded_text(
                    _extract(
                        raw_result,
                        "grading_policy_version",
                        "",
                    ),
                    field_name=(
                        f"results[{index}].grading_policy_version"
                    ),
                ),
                computation_reference=_bounded_text(
                    _extract(
                        raw_result,
                        "computation_reference",
                        "",
                    ),
                    field_name=(
                        f"results[{index}].computation_reference"
                    ),
                ),
            )
        )

    return normalised


def _fetch_transcript_results(
    student: Any,
    terms: Sequence[Any],
) -> list[TermTranscriptResult]:
    """
    Fetch authoritative GPA and credit results from Academics/Grading.

    No GPA or cumulative GPA calculation occurs in Reports.
    """
    provider = _load_provider()

    try:
        raw_results = provider(
            student=student,
            terms=tuple(terms),
        )
    except TypeError as exc:
        raise ImproperlyConfigured(
            "The configured transcript provider must accept keyword "
            "arguments 'student' and 'terms'."
        ) from exc

    return _normalise_provider_results(
        raw_results,
        terms,
    )


def _snapshot_from_result(
    *,
    transcript: TranscriptRecord,
    result: TermTranscriptResult,
) -> TranscriptGPASnapshot:
    snapshot = TranscriptGPASnapshot(
        transcript=transcript,
        term=result.term,
        term_gpa=result.term_gpa,
        cumulative_gpa=result.cumulative_gpa,
        credits_earned=result.credits_earned,
    )

    optional_values = {
        "credits_attempted": result.credits_attempted,
        "grade_points": result.grade_points,
        "academic_standing": result.academic_standing,
        "grading_policy_version": result.grading_policy_version,
        "computation_reference": result.computation_reference,
    }

    for field_name, value in optional_values.items():
        if hasattr(snapshot, field_name):
            setattr(snapshot, field_name, value)

    snapshot.full_clean()
    return snapshot


def _apply_transcript_totals(
    *,
    transcript: TranscriptRecord,
    results: Sequence[TermTranscriptResult],
) -> list[str]:
    update_fields: list[str] = []

    if results:
        transcript.cumulative_gpa = results[-1].cumulative_gpa
        transcript.credits_earned_total = sum(
            (
                result.credits_earned
                for result in results
            ),
            Decimal("0"),
        )
        update_fields.extend(
            ["cumulative_gpa", "credits_earned_total"]
        )

    transcript.status = GeneratedReportStatus.READY
    update_fields.append("status")

    if hasattr(transcript, "completed_at"):
        transcript.completed_at = timezone.now()
        update_fields.append("completed_at")

    transcript.full_clean()
    transcript.save(update_fields=update_fields)
    return update_fields


def _create_snapshots(
    *,
    transcript: TranscriptRecord,
    results: Sequence[TermTranscriptResult],
) -> list[TranscriptGPASnapshot]:
    snapshots = [
        _snapshot_from_result(
            transcript=transcript,
            result=result,
        )
        for result in results
    ]

    TranscriptGPASnapshot.objects.bulk_create(snapshots)
    return snapshots


@transaction.atomic
def generate_transcript(
    *,
    student: Any,
    school: Any,
    terms: Iterable[Any],
    is_official: bool,
    issued_by: Any,
) -> TranscriptRecord:
    ordered_terms = _normalise_terms(terms)

    _validate_context(
        student=student,
        school=school,
        terms=ordered_terms,
        actor=issued_by,
        actor_field_name="issued_by",
    )

    results = _fetch_transcript_results(
        student,
        ordered_terms,
    )

    transcript = TranscriptRecord(
        school=school,
        student=student,
        is_official=bool(is_official),
        verification_code=generate_verification_code(),
        issued_by=issued_by,
        status=GeneratedReportStatus.PROCESSING,
    )

    if hasattr(transcript, "issued_at"):
        transcript.issued_at = timezone.now()

    transcript.full_clean()
    transcript.save()

    _create_snapshots(
        transcript=transcript,
        results=results,
    )
    _apply_transcript_totals(
        transcript=transcript,
        results=results,
    )

    logger.info(
        "Generated transcript %s for student %s with %s terms.",
        transcript.pk,
        student.pk,
        len(results),
    )
    return transcript


@transaction.atomic
def regenerate_transcript(
    *,
    previous: TranscriptRecord,
    reason: str,
    terms: Iterable[Any],
    generated_by: Any,
) -> TranscriptRecord:
    if getattr(previous, "pk", None) is None:
        raise ValidationError(
            "A persisted transcript is required."
        )

    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError(
            "regeneration_reason is required."
        )

    ordered_terms = _normalise_terms(terms)

    previous = (
        TranscriptRecord.objects
        .select_for_update()
        .select_related("student", "school")
        .get(pk=previous.pk)
    )

    if previous.is_revoked:
        raise ValidationError(
            "A revoked transcript cannot be regenerated."
        )

    if not previous.is_latest:
        raise ValidationError(
            "Only the latest transcript version can be regenerated."
        )

    _validate_context(
        student=previous.student,
        school=previous.school,
        terms=ordered_terms,
        actor=generated_by,
        actor_field_name="generated_by",
    )

    results = _fetch_transcript_results(
        previous.student,
        ordered_terms,
    )

    new_transcript = versioning_service.create_new_version(
        previous_instance=previous,
        reason=reason,
        generated_by=generated_by,
        extra_fields={
            "verification_code": generate_verification_code(),
            "status": GeneratedReportStatus.PROCESSING,
            "cumulative_gpa": None,
            "credits_earned_total": Decimal("0"),
        },
    )

    _create_snapshots(
        transcript=new_transcript,
        results=results,
    )
    _apply_transcript_totals(
        transcript=new_transcript,
        results=results,
    )

    logger.info(
        "Regenerated transcript %s from transcript %s.",
        new_transcript.pk,
        previous.pk,
    )
    return new_transcript


@transaction.atomic
def revoke_transcript(
    *,
    transcript: TranscriptRecord,
    reason: str,
    revoked_by: Any,
) -> TranscriptRecord:
    if getattr(transcript, "pk", None) is None:
        raise ValidationError(
            "A persisted transcript is required."
        )

    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("revocation reason is required.")

    locked = (
        TranscriptRecord.objects
        .select_for_update()
        .select_related("school")
        .get(pk=transcript.pk)
    )

    if locked.is_revoked:
        raise ValidationError(
            "Transcript has already been revoked."
        )

    _validate_actor(
        actor=revoked_by,
        school_id=locked.school_id,
        field_name="revoked_by",
    )

    revoked = versioning_service.revoke(
        instance=locked,
        reason=reason,
        revoked_by=revoked_by,
    )

    logger.warning(
        "Revoked transcript %s.",
        locked.pk,
    )
    return revoked


def verify(verification_code: str) -> dict[str, Any]:
    """
    Verify a transcript without exposing unnecessary student information.
    """
    if (
        not isinstance(verification_code, str)
        or not verification_code.strip()
    ):
        return {"result": VerificationResult.NOT_FOUND}

    transcript = (
        TranscriptRecord.objects
        .only(
            "id",
            "verification_code",
            "is_official",
            "cumulative_gpa",
            "is_revoked",
            "is_latest",
        )
        .filter(
            verification_code=verification_code.strip(),
        )
        .first()
    )

    if transcript is None:
        return {"result": VerificationResult.NOT_FOUND}

    if transcript.is_revoked:
        return {"result": VerificationResult.REVOKED}

    if not transcript.is_latest:
        return {"result": VerificationResult.SUPERSEDED}

    return {
        "result": VerificationResult.VALID,
        "transcript_id": transcript.pk,
        "is_official": transcript.is_official,
        "cumulative_gpa": transcript.cumulative_gpa,
    }