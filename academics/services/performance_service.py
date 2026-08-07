"""
Canonical academic performance service.

This module is the single place that turns approved marks into subject
scores, grades, GPA, and rankings. Nothing outside this module (and the
grading models it reads) may independently calculate marks, grades,
GPA, aggregates, averages, or positions. The reports app must consume
this service's output and freeze it -- it must never recompute academic
figures itself.

Location note: settings.REPORTS_PERFORMANCE_PROVIDER already points at
"academics.services.performance_service.get_student_performance" (see
schoolsys/settings.py), alongside REPORTS_RESULT_SLIP_PROVIDER and
REPORTS_TRANSCRIPT_PROVIDER, which use the same academics.services.*
convention. This module keeps that existing convention rather than
moving the implementation into grading.services, so all three
providers stay consistent. The actual score/grade/weight computation
below still lives against grading's models (Grade, Assessment,
AssessmentType, GradingScale) -- academics does not duplicate or
reimplement grading's data, it just imports it, the same direction
grading already imports academics.models (ClassroomSubject,
StudentEnrollment).

DOCUMENTED POLICY DECISIONS (need project-owner review before this is
treated as final for official documents):

1. Weight normalisation for partial coverage. AssessmentType.weight_percentage
   is school-wide per type (e.g. "Test" = 30%, "Exam" = 70%), not guaranteed
   to sum to 100 for any given subject's *actual* assessments (a subject may
   not have every type graded yet). This implementation normalises: it sums
   weighted scores only for assessment types that have at least one approved
   grade, then divides by the weight actually covered so a partially-graded
   subject still reports a 0-100 score. `weight_covered_percentage` is
   reported per subject so an incomplete subject is visible to callers,
   rather than silently guessed at.

2. Multiple assessments of the same type (e.g. two "Test" entries) are
   averaged within that type before the type's weight is applied once --
   otherwise the same weight would be double-counted.

3. Ranking (class_position, subject_position) uses standard competition
   ranking ("1224"): equal scores get the same rank, and the next distinct
   score's rank skips the number of tied entries. Students with no
   computable score are excluded from ranking and from class_size.

4. Grade symbol / grade_point / pass-fail all come from GradingScale /
   GradeBoundary. No boundaries are hard-coded anywhere in this module. If
   a school has no active GradingScale configured, grade/remark/gpa/
   pass_fail_status are returned as None/"UNGRADED" rather than guessed.

5. "aggregate" (e.g. O-level best-N-subjects aggregate points) is not
   computed here -- it depends on a school-specific subject-selection
   policy that does not exist anywhere in this project yet. It is always
   returned as None until that policy is defined and approved.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db.models import Prefetch


ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO_PLACES = Decimal("0.01")


class PerformanceServiceError(Exception):
    """Raised for invalid input to the performance service."""


def _round2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _validate_same_school(student: Any, term: Any) -> None:
    student_school_id = getattr(student, "school_id", None)
    term_school_id = getattr(term, "school_id", None)

    if student_school_id is None or term_school_id is None:
        raise PerformanceServiceError(
            "Both student and term must be persisted, school-scoped records."
        )

    if student_school_id != term_school_id:
        raise PerformanceServiceError(
            "The student and term belong to different schools."
        )


def _active_grading_scale(school_id: int):
    from grading.models import GradingScale

    return (
        GradingScale.objects.filter(school_id=school_id, is_active=True)
        .prefetch_related("boundaries")
        .first()
    )


def _boundary_for_percentage(scale, percentage: Decimal | None):
    if scale is None or percentage is None:
        return None
    for boundary in scale.boundaries.all():
        if boundary.min_percentage <= percentage <= boundary.max_percentage:
            return boundary
    return None


def _student_enrollments_for_term(student, term):
    from academics.models import StudentEnrollment

    return (
        StudentEnrollment.objects.filter(
            student=student,
            is_active=True,
            classroom_subject__academic_term=term,
            classroom_subject__school_id=student.school_id,
        )
        .select_related(
            "classroom_subject",
            "classroom_subject__subject",
            "classroom_subject__classroom",
        )
        .order_by("classroom_subject__subject__name")
    )


def _approved_grades_by_assessment_type(enrollment):
    """
    Return {assessment_type_id: [(percentage, weight_percentage, assessment), ...]}
    for one enrollment's approved grades only.
    """
    from grading.models import GradeStatus

    grades = (
        enrollment.grades.filter(status=GradeStatus.APPROVED)
        .select_related("assessment", "assessment__assessment_type")
    )

    by_type: dict[int, list[tuple[Decimal, Decimal, Any]]] = {}
    for grade in grades:
        assessment_type = grade.assessment.assessment_type
        by_type.setdefault(assessment_type.id, []).append(
            (grade.percentage, assessment_type.weight_percentage, grade)
        )
    return by_type


def _score_subject(enrollment, scale) -> dict[str, Any]:
    subject = enrollment.classroom_subject.subject
    by_type = _approved_grades_by_assessment_type(enrollment)

    assessments_out: list[dict[str, Any]] = []
    weighted_total = ZERO
    weight_covered = ZERO

    for type_id, entries in by_type.items():
        weight_percentage = entries[0][1]
        type_percentage_sum = sum((p for p, _w, _g in entries), ZERO)
        type_percentage_avg = _round2(
            type_percentage_sum / Decimal(len(entries))
        )
        weighted_score = _round2(
            type_percentage_avg * weight_percentage / HUNDRED
        )
        weighted_total += weighted_score
        weight_covered += weight_percentage

        for percentage, _weight, grade in entries:
            assessments_out.append({
                "assessment_id": grade.assessment_id,
                "assessment_name": grade.assessment.title,
                "assessment_type": grade.assessment.assessment_type.name,
                "raw_score": grade.score,
                "maximum_score": grade.assessment.maximum_score,
                "percentage": percentage,
                "weight_percentage": weight_percentage,
                "weighted_score": _round2(
                    percentage * weight_percentage / HUNDRED
                ),
            })

    if weight_covered > ZERO:
        final_score = _round2(weighted_total / (weight_covered / HUNDRED))
    else:
        final_score = None

    boundary = _boundary_for_percentage(scale, final_score)

    return {
        "subject_id": subject.id,
        "subject_code": subject.code,
        "subject_name": subject.name,
        "assessments": assessments_out,
        "final_score": final_score,
        "weight_covered_percentage": weight_covered,
        "grade": boundary.grade_symbol if boundary else None,
        "remark": boundary.remark if boundary else "",
        "is_passing": boundary.is_passing if boundary else None,
        "grade_point": boundary.grade_point if boundary else None,
        "subject_position": None,
        "enrollment_id": enrollment.id,
        "classroom_id": enrollment.classroom_subject.classroom_id,
    }


def _rank(scores: list[tuple[int, Decimal]]) -> dict[int, int]:
    """
    Standard competition ranking ("1224"), descending by score.
    Input: [(entity_id, score), ...]. Output: {entity_id: rank}.
    """
    ranked = sorted(scores, key=lambda pair: pair[1], reverse=True)
    positions: dict[int, int] = {}
    previous_score = None
    previous_rank = 0
    for index, (entity_id, score) in enumerate(ranked, start=1):
        if previous_score is not None and score == previous_score:
            positions[entity_id] = previous_rank
        else:
            positions[entity_id] = index
            previous_rank = index
            previous_score = score
    return positions


def _class_and_subject_positions(student, term, subjects, scale):
    """
    Rank this student's overall average and each subject's final_score
    against classmates sharing the same classroom for this term.
    Only enrollments/subjects with a computable final_score are ranked.
    """
    from academics.models import StudentEnrollment

    if not subjects:
        return None, None, None, {}

    classroom_id = subjects[0]["classroom_id"]

    peer_enrollments = (
        StudentEnrollment.objects.filter(
            is_active=True,
            classroom_subject__academic_term=term,
            classroom_subject__classroom_id=classroom_id,
        )
        .select_related("student", "classroom_subject__subject")
    )

    peers_by_student: dict[int, list] = {}
    for enrollment in peer_enrollments:
        peers_by_student.setdefault(enrollment.student_id, []).append(
            enrollment
        )

    overall_scores: list[tuple[int, Decimal]] = []
    subject_score_lists: dict[int, list[tuple[int, Decimal]]] = {}

    for peer_student_id, enrollments in peers_by_student.items():
        peer_subject_scores = []
        for enrollment in enrollments:
            by_type = _approved_grades_by_assessment_type(enrollment)
            weighted_total = ZERO
            weight_covered = ZERO
            for entries in by_type.values():
                weight_percentage = entries[0][1]
                avg_percentage = _round2(
                    sum((p for p, _w, _g in entries), ZERO)
                    / Decimal(len(entries))
                )
                weighted_total += _round2(
                    avg_percentage * weight_percentage / HUNDRED
                )
                weight_covered += weight_percentage

            if weight_covered > ZERO:
                score = _round2(weighted_total / (weight_covered / HUNDRED))
                subject_id = enrollment.classroom_subject.subject_id
                peer_subject_scores.append(score)
                subject_score_lists.setdefault(subject_id, []).append(
                    (peer_student_id, score)
                )

        if peer_subject_scores:
            peer_average = _round2(
                sum(peer_subject_scores, ZERO)
                / Decimal(len(peer_subject_scores))
            )
            overall_scores.append((peer_student_id, peer_average))

    class_size = len(overall_scores)
    class_average = (
        _round2(sum((s for _id, s in overall_scores), ZERO) / Decimal(class_size))
        if class_size
        else None
    )
    class_positions = _rank(overall_scores)
    class_position = class_positions.get(student.id)

    subject_positions: dict[str, Any] = {}
    for subject in subjects:
        subject_id = subject["subject_id"]
        score_list = subject_score_lists.get(subject_id, [])
        positions = _rank(score_list)
        position = positions.get(student.id)
        subject["subject_position"] = position
        subject_positions[subject["subject_code"]] = {
            "position": position,
            "class_size": len(score_list) or None,
        }

    return class_position, class_size, class_average, subject_positions


def get_student_performance(*, student: Any, term: Any) -> dict[str, Any]:
    """
    Canonical, read-only academic performance for one student in one term.

    Uses only approved grades (grading.models.GradeStatus.APPROVED). Never
    writes to any model. Deterministic for the same approved data.
    """
    if getattr(student, "pk", None) is None:
        raise PerformanceServiceError("A persisted student is required.")
    if getattr(term, "pk", None) is None:
        raise PerformanceServiceError("A persisted academic term is required.")

    _validate_same_school(student, term)

    scale = _active_grading_scale(student.school_id)

    enrollments = _student_enrollments_for_term(student, term)
    subjects = [_score_subject(enrollment, scale) for enrollment in enrollments]

    (
        class_position,
        class_size,
        class_average,
        subject_positions,
    ) = _class_and_subject_positions(student, term, subjects, scale)

    computable = [s["final_score"] for s in subjects if s["final_score"] is not None]
    average = (
        _round2(sum(computable, ZERO) / Decimal(len(computable)))
        if computable
        else None
    )

    gpa = None
    grade_points = [
        s["grade_point"] for s in subjects if s.get("grade_point") is not None
    ]
    if grade_points:
        gpa = _round2(sum(grade_points, ZERO) / Decimal(len(grade_points)))

    if not subjects:
        pass_fail_status = "NO_SUBJECTS"
    elif scale is None:
        pass_fail_status = "UNGRADED"
    else:
        failing = [
            s for s in subjects
            if s["final_score"] is not None and s.get("is_passing") is False
        ]
        incomplete = [s for s in subjects if s["final_score"] is None]
        if incomplete:
            pass_fail_status = "INCOMPLETE"
        elif failing:
            pass_fail_status = "FAIL"
        else:
            pass_fail_status = "PASS"

    return {
        "student_id": student.id,
        "term_id": term.id,
        "grading_policy_version": (
            f"scale:{scale.id}:{scale.name}" if scale else "unconfigured"
        ),
        "computation_reference": f"student:{student.id}:term:{term.id}",

        "subjects": subjects,

        "average": average,
        "gpa": gpa,
        "aggregate": None,  # see module docstring, item 5
        "class_position": class_position,
        "class_size": class_size,
        "class_average": class_average,
        "school_average": None,
        "subject_positions": subject_positions,
        "pass_fail_status": pass_fail_status,
        "performance_summary": {
            "subjects_graded": len(computable),
            "subjects_enrolled": len(subjects),
        },
    }
