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


def _room_list_rows(seating_plan: SeatingPlan) -> list[tuple[str, str, str, str, str]]:
    assignments = (
        _base_assignments(seating_plan)
        .select_related("student__user")
        .order_by("seat_number")
    )

    rows = []
    for assignment in assignments:
        student_user = assignment.student.user
        student_name = (
            student_user.get_full_name().strip() or student_user.email
        )
        rows.append((
            assignment.seat_number,
            getattr(assignment.student, "student_id_number", ""),
            student_name,
            assignment.subject_or_paper,
            assignment.get_status_display(),
        ))
    return rows


def build_room_list_context(seating_plan: SeatingPlan) -> dict[str, Any]:
    """
    Build the render context for the room-list document/export.

    Shared by both the PDF template (reports/seating_list/room_list.html)
    and the Excel export, since both consume the same (seat, student_number,
    student_name, subject_or_paper, status) row tuples.
    """
    _validate_plan(seating_plan)
    school = seating_plan.school

    return {
        "room": seating_plan.room,
        "exam_date": seating_plan.exam_date,
        "start_time": seating_plan.start_time,
        "end_time": seating_plan.end_time,
        "capacity": seating_plan.capacity,
        "rows": _room_list_rows(seating_plan),
        "created_at": seating_plan.created_at,
        "school_name": school.name,
        "branding": {
            "school_name": school.name,
            "school_address": getattr(school, "address", "") or "",
            "school_phone": getattr(school, "phone", "") or "",
            "school_email": getattr(school, "email", "") or "",
            "font_family": "DejaVu Sans, Arial, sans-serif",
            "heading_font_family": "Georgia, Times New Roman, serif",
            "font_size_base": "10.5pt",
            "watermark_text": school.name,
            "colors": {
                "primary": "#173b63",
                "secondary": "#5f6976",
                "accent": "#d3aa4d",
            },
        },
        "page_config": {
            "page_size": "A4",
            "orientation": "landscape",
            "margins": {
                "top": "12mm",
                "right": "12mm",
                "bottom": "12mm",
                "left": "12mm",
            },
        },
        "layout_config": {},
    }


def export_room_list(
    *,
    seating_plan: SeatingPlan,
    requested_by: Any,
    export_format: str = "PDF",
) -> tuple[bytes, str, str]:
    """
    Render the room list as a downloadable file.

    Returns ``(file_bytes, sha256_hash, content_type)``. Supports PDF
    (the room_list.html template) and EXCEL (a flat headers/rows sheet).
    The caller is responsible for authorizing ``requested_by`` against
    ``seating_plan.school`` before calling this function.
    """
    from reports.services import export_service

    _validate_plan(seating_plan)
    normalised_format = str(export_format or "PDF").strip().upper()

    if normalised_format == "EXCEL":
        report_data = {
            "sheet_name": f"Room {seating_plan.room}",
            "headers": [
                "Seat", "Student No.", "Student Name", "Subject / Paper", "Status",
            ],
            "rows": _room_list_rows(seating_plan),
        }
        content_type = (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        )
    elif normalised_format == "PDF":
        report_data = {
            **build_room_list_context(seating_plan),
            "template_path": "reports/seating_list/room_list.html",
        }
        content_type = "application/pdf"
    else:
        raise ValidationError(
            f"Unsupported room list export format: {export_format!r}."
        )

    file_bytes, file_hash = export_service.export(
        report_data=report_data,
        export_format=normalised_format,
    )
    return file_bytes, file_hash, content_type


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