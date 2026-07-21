"""
Production examination administration reporting service.

Provides validated query helpers and export contexts for seating plans.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Count

from reports.constants import SeatAssignmentStatus
from reports.exceptions import ValidationError
from reports.models.seating import (
    InvigilatorAssignment,
    SeatAssignment,
    SeatingPlan,
)


def _validate_plan(seating_plan: SeatingPlan) -> None:
    if getattr(seating_plan, "pk", None) is None:
        raise ValidationError("A persisted seating plan is required.")


def _base_assignments(seating_plan: SeatingPlan):
    _validate_plan(seating_plan)
    return (
        SeatAssignment.objects.filter(seating_plan=seating_plan)
        .select_related("student")
        .order_by("seat_number", "id")
    )


def get_room_list(seating_plan: SeatingPlan):
    return _base_assignments(seating_plan)


def get_candidate_list(seating_plan: SeatingPlan):
    return _base_assignments(seating_plan)


def get_missing_candidates(seating_plan: SeatingPlan):
    return _base_assignments(seating_plan).filter(
        status=SeatAssignmentStatus.MISSING_CANDIDATE
    )


def get_special_needs_candidates(seating_plan: SeatingPlan):
    return (
        _base_assignments(seating_plan)
        .exclude(special_needs_accommodation__isnull=True)
        .exclude(special_needs_accommodation="")
    )


def get_invigilators(seating_plan: SeatingPlan):
    _validate_plan(seating_plan)
    return (
        InvigilatorAssignment.objects.filter(seating_plan=seating_plan)
        .select_related("staff")
        .order_by("id")
    )


@transaction.atomic
def mark_missing_candidates(
    seating_plan: SeatingPlan,
    present_student_ids: set[int],
) -> int:
    _validate_plan(seating_plan)

    if present_student_ids is None:
        present_student_ids = set()

    if not isinstance(present_student_ids, set):
        present_student_ids = set(present_student_ids)

    locked = (
        SeatAssignment.objects
        .select_for_update()
        .filter(seating_plan=seating_plan)
    )

    return locked.exclude(
        student_id__in=present_student_ids
    ).exclude(
        status=SeatAssignmentStatus.MISSING_CANDIDATE
    ).update(
        status=SeatAssignmentStatus.MISSING_CANDIDATE
    )


def build_room_list_export_context(
    seating_plan: SeatingPlan,
) -> dict[str, Any]:
    assignments = list(get_room_list(seating_plan))

    headers = [
        "Seat",
        "Student Number",
        "Student Name",
        "Subject/Paper",
        "Status",
    ]

    rows = [
        [
            assignment.seat_number,
            getattr(assignment.student, "student_number", ""),
            getattr(
                assignment.student,
                "full_name",
                str(assignment.student),
            ),
            assignment.subject_or_paper,
            assignment.status,
        ]
        for assignment in assignments
    ]

    summary = (
        SeatAssignment.objects.filter(seating_plan=seating_plan)
        .values("status")
        .annotate(total=Count("id"))
        .order_by("status")
    )

    return {
        "headers": headers,
        "rows": rows,
        "sheet_name": f"Room {seating_plan.room}",
        "title": f"Room List - {seating_plan.room}",
        "generated_from": seating_plan.pk,
        "summary": list(summary),
        "record_count": len(rows),
    }