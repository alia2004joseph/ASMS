"""
Comprehensive tests for examination seating models.

Expected model module:
    reports.models.seating

If your source file has a different name, update this import:

    from reports.models.seating import (
        SeatingPlan,
        SeatAssignment,
        InvigilatorAssignment,
    )

Recommended location:
    reports/tests/test_seating.py

Run:
    pytest reports/tests/test_seating.py -q
"""

from datetime import date, time
import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from accounts.models import StudentProfile, User
from reports.constants import InvigilatorRole, SeatAssignmentStatus
from reports.models.base import (
    AuditableModel,
    SchoolScopedManager,
    SchoolScopedModel,
    SchoolScopedQuerySet,
)
from reports.models.seating import (
    InvigilatorAssignment,
    SeatAssignment,
    SeatingPlan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNSET = object()


def model_field(model, name):
    return model._meta.get_field(name)


def index_map(model):
    return {
        index.name: tuple(index.fields)
        for index in model._meta.indexes
    }


def constraint_map(model):
    return {
        constraint.name: constraint
        for constraint in model._meta.constraints
    }


def make_plan(
    *,
    pk=1,
    school_id=10,
    external_reference=_UNSET,
    room="Main Hall",
    exam_date=date(2026, 8, 12),
    start_time=time(9, 0),
    end_time=time(11, 0),
    capacity=100,
    is_active=True,
    created_by_id=None,
):
    plan = SeatingPlan(
        school_id=school_id,
        external_reference=(
            {"exam_session_id": 42}
            if external_reference is _UNSET
            else external_reference
        ),
        room=room,
        exam_date=exam_date,
        start_time=start_time,
        end_time=end_time,
        capacity=capacity,
        is_active=is_active,
        created_by_id=created_by_id,
    )
    plan.pk = pk
    return plan


def make_student(
    *,
    pk=20,
    school_id=10,
    label="Student One",
    student_id_number="STU-001",
):
    """
    Return a real, unsaved StudentProfile instance.

    Django ForeignKey descriptors require an instance of the exact related
    model. Unsaved model instances are sufficient for these unit-level clean()
    and __str__ tests, so no database access is required.
    """
    user = User(
        pk=pk,
        email=f"student{pk}@example.com",
        first_name=label,
        role=User.Role.STUDENT,
        school_id=school_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    )

    return StudentProfile(
        pk=pk,
        user=user,
        school_id=school_id,
        student_id_number=student_id_number,
        is_active_student=True,
    )


def make_printable_student(
    *,
    pk=20,
    school_id=10,
    label="Student One",
):
    return make_student(
        pk=pk,
        school_id=school_id,
        label=label,
    )


def make_staff(
    *,
    pk=30,
    school_id=10,
    is_active=True,
    label="Staff User",
):
    return User(
        pk=pk,
        email=f"staff{pk}@example.com",
        first_name=label,
        role=User.Role.TEACHER,
        school_id=school_id,
        is_active=is_active,
        approval_status=User.ApprovalStatus.APPROVED,
    )


def make_seat_assignment(
    *,
    pk=1,
    plan=None,
    student=None,
    seat_number="A-01",
    subject_or_paper="Mathematics Paper 1",
    special_needs_accommodation="",
    status=SeatAssignmentStatus.ASSIGNED,
):
    plan = plan or make_plan()
    student = student or make_printable_student(
        school_id=plan.school_id
    )

    assignment = SeatAssignment(
        seating_plan=plan,
        student=student,
        seat_number=seat_number,
        subject_or_paper=subject_or_paper,
        special_needs_accommodation=special_needs_accommodation,
        status=status,
    )
    assignment.pk = pk
    return assignment


def make_invigilator_assignment(
    *,
    pk=1,
    plan=None,
    staff=None,
    role=InvigilatorRole.ASSISTANT,
    is_active=True,
):
    plan = plan or make_plan()
    staff = staff or make_staff(school_id=plan.school_id)

    assignment = InvigilatorAssignment(
        seating_plan=plan,
        staff=staff,
        role=role,
        is_active=is_active,
    )
    assignment.pk = pk
    return assignment


# ===========================================================================
# SeatingPlan
# ===========================================================================


class TestSeatingPlanInheritance:
    def test_inherits_school_scoped_model(self):
        assert issubclass(SeatingPlan, SchoolScopedModel)

    def test_inherits_auditable_model(self):
        assert issubclass(SeatingPlan, AuditableModel)

    def test_uses_school_scoped_manager(self):
        assert isinstance(SeatingPlan.objects, SchoolScopedManager)

    def test_manager_returns_school_scoped_queryset(self):
        assert isinstance(
            SeatingPlan.objects.get_queryset(),
            SchoolScopedQuerySet,
        )


class TestSeatingPlanFieldTypes:
    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("school", models.ForeignKey),
            ("created_by", models.ForeignKey),
            ("created_at", models.DateTimeField),
            ("updated_at", models.DateTimeField),
            ("external_reference", models.JSONField),
            ("room", models.CharField),
            ("exam_date", models.DateField),
            ("start_time", models.TimeField),
            ("end_time", models.TimeField),
            ("capacity", models.PositiveIntegerField),
            ("is_active", models.BooleanField),
        ],
    )
    def test_field_type(self, name, expected_type):
        assert isinstance(model_field(SeatingPlan, name), expected_type)


class TestSeatingPlanFieldMetadata:
    def test_external_reference_default_is_dict(self):
        field = model_field(SeatingPlan, "external_reference")
        assert field.default is dict

    def test_external_reference_allows_blank(self):
        assert model_field(
            SeatingPlan,
            "external_reference",
        ).blank is True

    def test_external_reference_help_text(self):
        help_text = model_field(
            SeatingPlan,
            "external_reference",
        ).help_text

        assert "external examination session" in help_text
        assert "exam_session_id" in help_text

    def test_room_max_length(self):
        assert model_field(SeatingPlan, "room").max_length == 100

    def test_exam_date_is_indexed(self):
        assert model_field(SeatingPlan, "exam_date").db_index is True

    def test_capacity_help_text(self):
        assert (
            model_field(SeatingPlan, "capacity").help_text
            == "Maximum number of candidates permitted in this room."
        )

    def test_is_active_default(self):
        assert model_field(SeatingPlan, "is_active").default is True

    def test_is_active_is_indexed(self):
        assert model_field(SeatingPlan, "is_active").db_index is True

    def test_school_uses_cascade(self):
        assert (
            model_field(SeatingPlan, "school").remote_field.on_delete
            is models.CASCADE
        )

    def test_created_by_is_optional(self):
        field = model_field(SeatingPlan, "created_by")
        assert field.null is True
        assert field.blank is True

    def test_created_by_uses_set_null(self):
        assert (
            model_field(SeatingPlan, "created_by")
            .remote_field.on_delete
            is models.SET_NULL
        )

    def test_created_at_uses_callable_default(self):
        field = model_field(SeatingPlan, "created_at")

        assert callable(field.default)
        assert field.auto_now_add is False
        assert field.editable is False
        assert field.db_index is True

    def test_updated_at_is_auto_now(self):
        assert model_field(
            SeatingPlan,
            "updated_at",
        ).auto_now is True


class TestSeatingPlanDefaults:
    def test_default_external_reference_is_empty_dict(self):
        assert SeatingPlan().external_reference == {}

    def test_external_reference_defaults_are_not_shared(self):
        first = SeatingPlan()
        second = SeatingPlan()

        first.external_reference["exam_session_id"] = 99

        assert second.external_reference == {}

    def test_is_active_defaults_to_true(self):
        assert SeatingPlan().is_active is True

    def test_accepts_nested_external_reference(self):
        reference = {
            "exam_session_id": 42,
            "exam_id": 12,
            "source": "examinations",
            "metadata": {"term": 1},
        }

        plan = make_plan(external_reference=reference)

        assert plan.external_reference == reference


class TestSeatingPlanMeta:
    def test_ordering(self):
        assert SeatingPlan._meta.ordering == [
            "exam_date",
            "start_time",
            "room",
        ]

    def test_constraint_names(self):
        assert set(constraint_map(SeatingPlan)) == {
            "seating_plan_capacity_gte_1",
            "seating_plan_end_after_start",
            "unique_room_exam_session",
        }

    def test_capacity_constraint_type(self):
        constraint = constraint_map(SeatingPlan)[
            "seating_plan_capacity_gte_1"
        ]
        assert isinstance(constraint, models.CheckConstraint)

    def test_end_time_constraint_type(self):
        constraint = constraint_map(SeatingPlan)[
            "seating_plan_end_after_start"
        ]
        assert isinstance(constraint, models.CheckConstraint)

    def test_unique_room_constraint_type(self):
        constraint = constraint_map(SeatingPlan)[
            "unique_room_exam_session"
        ]
        assert isinstance(constraint, models.UniqueConstraint)

    def test_unique_room_constraint_fields(self):
        constraint = constraint_map(SeatingPlan)[
            "unique_room_exam_session"
        ]
        assert tuple(constraint.fields) == (
            "school",
            "room",
            "exam_date",
            "start_time",
        )

    def test_capacity_constraint_condition(self):
        constraint = constraint_map(SeatingPlan)[
            "seating_plan_capacity_gte_1"
        ]
        assert constraint.condition == Q(capacity__gte=1)

    def test_end_time_constraint_condition(self):
        constraint = constraint_map(SeatingPlan)[
            "seating_plan_end_after_start"
        ]
        assert constraint.condition == Q(
            end_time__gt=F("start_time")
        )

    def test_index_names(self):
        assert set(index_map(SeatingPlan)) == {
            "seating_school_date_idx",
            "seating_plan_school_active_idx",
        }

    def test_school_date_room_index(self):
        assert index_map(SeatingPlan)[
            "seating_school_date_idx"
        ] == (
            "school",
            "exam_date",
            "room",
        )

    def test_school_date_active_index(self):
        assert index_map(SeatingPlan)[
            "seating_plan_school_active_idx"
        ] == (
            "school",
            "exam_date",
            "is_active",
        )


class TestSeatingPlanValidation:
    def test_valid_plan_passes_clean(self):
        make_plan().clean()

    @pytest.mark.parametrize("capacity", [1, 2, 50, 1000])
    def test_positive_capacity_is_valid(self, capacity):
        make_plan(capacity=capacity).clean()

    @pytest.mark.parametrize("capacity", [0, -1, -50])
    def test_capacity_below_one_is_invalid(self, capacity):
        plan = make_plan(capacity=capacity)

        with pytest.raises(ValidationError) as exc_info:
            plan.clean()

        assert exc_info.value.message_dict["capacity"] == [
            "Room capacity must be at least 1."
        ]

    def test_none_capacity_does_not_trigger_custom_error(self):
        plan = make_plan(capacity=None)

        plan.clean()

    def test_end_time_after_start_is_valid(self):
        plan = make_plan(
            start_time=time(8, 30),
            end_time=time(9, 0),
        )

        plan.clean()

    def test_equal_start_and_end_time_is_invalid(self):
        plan = make_plan(
            start_time=time(9, 0),
            end_time=time(9, 0),
        )

        with pytest.raises(ValidationError) as exc_info:
            plan.clean()

        assert exc_info.value.message_dict["end_time"] == [
            "The examination end time must be later than the start time."
        ]

    def test_end_time_before_start_is_invalid(self):
        plan = make_plan(
            start_time=time(12, 0),
            end_time=time(10, 0),
        )

        with pytest.raises(ValidationError) as exc_info:
            plan.clean()

        assert exc_info.value.message_dict["end_time"] == [
            "The examination end time must be later than the start time."
        ]

    def test_missing_start_time_skips_custom_time_error(self):
        plan = make_plan(start_time=None, end_time=time(10, 0))

        plan.clean()

    def test_missing_end_time_skips_custom_time_error(self):
        plan = make_plan(start_time=time(9, 0), end_time=None)

        plan.clean()

    @pytest.mark.parametrize(
        "invalid_reference",
        [
            [],
            (),
            "exam_session_id=42",
            42,
            True,
            None,
        ],
    )
    def test_external_reference_must_be_dict(
        self,
        invalid_reference,
    ):
        plan = make_plan(external_reference=invalid_reference)

        with pytest.raises(ValidationError) as exc_info:
            plan.clean()

        assert exc_info.value.message_dict[
            "external_reference"
        ] == ["External reference must be a JSON object."]

    @pytest.mark.parametrize(
        "valid_reference",
        [
            {},
            {"exam_session_id": 42},
            {"exam_id": 12, "source": "examinations"},
            {"nested": {"value": 1}},
        ],
    )
    def test_dict_external_reference_is_valid(
        self,
        valid_reference,
    ):
        make_plan(external_reference=valid_reference).clean()

    def test_clean_collects_all_errors(self):
        plan = make_plan(
            capacity=0,
            start_time=time(10, 0),
            end_time=time(9, 0),
            external_reference=[],
        )

        with pytest.raises(ValidationError) as exc_info:
            plan.clean()

        assert exc_info.value.message_dict == {
            "capacity": ["Room capacity must be at least 1."],
            "end_time": [
                "The examination end time must be later than the start time."
            ],
            "external_reference": [
                "External reference must be a JSON object."
            ],
        }


class TestSeatingPlanString:
    def test_string_representation(self):
        plan = make_plan(
            room="Room B",
            exam_date=date(2026, 9, 3),
            start_time=time(8, 5),
        )

        assert str(plan) == "Room B — 2026-09-03 08:05"

    @pytest.mark.parametrize(
        ("start_time", "expected"),
        [
            (time(0, 0), "00:00"),
            (time(8, 5), "08:05"),
            (time(12, 30), "12:30"),
            (time(23, 59), "23:59"),
        ],
    )
    def test_time_format_is_24_hour(
        self,
        start_time,
        expected,
    ):
        plan = make_plan(start_time=start_time)

        assert str(plan).endswith(expected)


# ===========================================================================
# SeatAssignment
# ===========================================================================


class TestSeatAssignmentInheritance:
    def test_inherits_models_model(self):
        assert issubclass(SeatAssignment, models.Model)

    def test_does_not_inherit_school_scoped_model(self):
        assert not issubclass(SeatAssignment, SchoolScopedModel)


class TestSeatAssignmentFieldTypes:
    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("seating_plan", models.ForeignKey),
            ("student", models.ForeignKey),
            ("seat_number", models.CharField),
            ("subject_or_paper", models.CharField),
            ("special_needs_accommodation", models.TextField),
            ("status", models.CharField),
            ("created_at", models.DateTimeField),
            ("updated_at", models.DateTimeField),
        ],
    )
    def test_field_type(self, name, expected_type):
        assert isinstance(
            model_field(SeatAssignment, name),
            expected_type,
        )


class TestSeatAssignmentFieldMetadata:
    def test_seating_plan_uses_cascade(self):
        assert (
            model_field(SeatAssignment, "seating_plan")
            .remote_field.on_delete
            is models.CASCADE
        )

    def test_seating_plan_related_name(self):
        assert (
            model_field(SeatAssignment, "seating_plan")
            .remote_field.related_name
            == "seat_assignments"
        )

    def test_student_uses_protect(self):
        assert (
            model_field(SeatAssignment, "student")
            .remote_field.on_delete
            is models.PROTECT
        )

    def test_student_related_name(self):
        assert (
            model_field(SeatAssignment, "student")
            .remote_field.related_name
            == "exam_seat_assignments"
        )

    def test_seat_number_max_length(self):
        assert model_field(
            SeatAssignment,
            "seat_number",
        ).max_length == 20

    def test_subject_or_paper_max_length(self):
        assert model_field(
            SeatAssignment,
            "subject_or_paper",
        ).max_length == 150

    def test_subject_or_paper_help_text(self):
        assert (
            model_field(
                SeatAssignment,
                "subject_or_paper",
            ).help_text
            == "Frozen subject or examination-paper label."
        )

    def test_special_needs_defaults(self):
        field = model_field(
            SeatAssignment,
            "special_needs_accommodation",
        )
        assert field.blank is True
        assert field.default == ""

    def test_special_needs_help_text(self):
        help_text = model_field(
            SeatAssignment,
            "special_needs_accommodation",
        ).help_text

        assert "accessible seating" in help_text
        assert "additional space" in help_text

    def test_status_max_length(self):
        assert model_field(
            SeatAssignment,
            "status",
        ).max_length == 25

    def test_status_choices(self):
        assert (
            list(model_field(SeatAssignment, "status").choices)
            == list(SeatAssignmentStatus.choices)
        )

    def test_status_default(self):
        assert (
            model_field(SeatAssignment, "status").default
            == SeatAssignmentStatus.ASSIGNED
        )

    def test_status_is_indexed(self):
        assert model_field(
            SeatAssignment,
            "status",
        ).db_index is True

    def test_created_at_auto_now_add(self):
        assert model_field(
            SeatAssignment,
            "created_at",
        ).auto_now_add is True

    def test_updated_at_auto_now(self):
        assert model_field(
            SeatAssignment,
            "updated_at",
        ).auto_now is True


class TestSeatAssignmentDefaults:
    def test_status_defaults_to_assigned(self):
        assert (
            SeatAssignment().status
            == SeatAssignmentStatus.ASSIGNED
        )

    def test_special_needs_defaults_to_empty_string(self):
        assert (
            SeatAssignment().special_needs_accommodation
            == ""
        )


class TestSeatAssignmentMeta:
    def test_ordering(self):
        assert SeatAssignment._meta.ordering == ["seat_number"]

    def test_constraint_names(self):
        assert set(constraint_map(SeatAssignment)) == {
            "unique_seat_per_plan",
            "unique_student_per_seating_plan",
        }

    def test_unique_seat_constraint(self):
        constraint = constraint_map(SeatAssignment)[
            "unique_seat_per_plan"
        ]

        assert isinstance(constraint, models.UniqueConstraint)
        assert tuple(constraint.fields) == (
            "seating_plan",
            "seat_number",
        )

    def test_unique_student_constraint(self):
        constraint = constraint_map(SeatAssignment)[
            "unique_student_per_seating_plan"
        ]

        assert isinstance(constraint, models.UniqueConstraint)
        assert tuple(constraint.fields) == (
            "seating_plan",
            "student",
        )

    def test_index_names(self):
        assert set(index_map(SeatAssignment)) == {
            "seat_plan_status_idx",
            "seat_plan_student_idx",
        }

    def test_plan_status_index(self):
        assert index_map(SeatAssignment)[
            "seat_plan_status_idx"
        ] == (
            "seating_plan",
            "status",
        )

    def test_plan_student_index(self):
        assert index_map(SeatAssignment)[
            "seat_plan_student_idx"
        ] == (
            "seating_plan",
            "student",
        )


class TestSeatAssignmentValidation:
    def test_valid_assignment_passes_clean(self):
        make_seat_assignment().clean()

    @pytest.mark.parametrize(
        "seat_number",
        ["A1", "A-01", "12", "Front-Left", "B 14"],
    )
    def test_non_blank_seat_number_is_valid(self, seat_number):
        make_seat_assignment(
            seat_number=seat_number,
        ).clean()

    @pytest.mark.parametrize(
        "seat_number",
        ["", " ", "   ", "\n", "\t"],
    )
    def test_blank_seat_number_is_invalid(self, seat_number):
        assignment = make_seat_assignment(
            seat_number=seat_number,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert exc_info.value.message_dict["seat_number"] == [
            "Seat number is required."
        ]

    def test_same_school_student_is_valid(self):
        plan = make_plan(school_id=44)
        student = make_printable_student(school_id=44)

        make_seat_assignment(
            plan=plan,
            student=student,
        ).clean()

    def test_different_school_student_is_invalid(self):
        plan = make_plan(school_id=44)
        student = make_printable_student(school_id=99)
        assignment = make_seat_assignment(
            plan=plan,
            student=student,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert exc_info.value.message_dict["student"] == [
            "The student must belong to the same school as the seating plan."
        ]

    def test_student_without_school_id_is_allowed(self):
        plan = make_plan(school_id=44)
        student = make_student(
            pk=1,
            school_id=None,
            label="Student",
        )

        make_seat_assignment(
            plan=plan,
            student=student,
        ).clean()

    def test_missing_plan_skips_school_validation(self):
        assignment = SeatAssignment(
            student_id=20,
            seat_number="A1",
            subject_or_paper="Physics",
        )

        assignment.clean()

    def test_missing_student_skips_school_validation(self):
        assignment = SeatAssignment(
            seating_plan=make_plan(),
            seat_number="A1",
            subject_or_paper="Physics",
        )

        assignment.clean()

    def test_clean_collects_seat_and_school_errors(self):
        plan = make_plan(school_id=10)
        student = make_printable_student(school_id=20)
        assignment = make_seat_assignment(
            plan=plan,
            student=student,
            seat_number=" ",
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert exc_info.value.message_dict == {
            "seat_number": ["Seat number is required."],
            "student": [
                "The student must belong to the same school as the seating plan."
            ],
        }


class TestSeatAssignmentString:
    def test_string_representation(self):
        plan = make_plan(
            room="Lab 2",
            exam_date=date(2026, 10, 5),
            start_time=time(14, 0),
        )
        student = make_printable_student(label="Alice")
        assignment = make_seat_assignment(
            plan=plan,
            student=student,
            seat_number="C-12",
        )

        assert str(assignment) == (
    "STU-001 - Alice (Student) "
    "— Seat C-12 "
    "(Lab 2 — 2026-10-05 14:00)"
)


class TestSeatAssignmentChoices:
    @pytest.mark.parametrize(
        ("value", "label"),
        SeatAssignmentStatus.choices,
    )
    def test_status_display(self, value, label):
        assignment = make_seat_assignment(status=value)

        assert assignment.get_status_display() == label


# ===========================================================================
# InvigilatorAssignment
# ===========================================================================


class TestInvigilatorAssignmentInheritance:
    def test_inherits_models_model(self):
        assert issubclass(
            InvigilatorAssignment,
            models.Model,
        )

    def test_does_not_inherit_school_scoped_model(self):
        assert not issubclass(
            InvigilatorAssignment,
            SchoolScopedModel,
        )


class TestInvigilatorAssignmentFieldTypes:
    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("seating_plan", models.ForeignKey),
            ("staff", models.ForeignKey),
            ("role", models.CharField),
            ("assigned_at", models.DateTimeField),
            ("is_active", models.BooleanField),
        ],
    )
    def test_field_type(self, name, expected_type):
        assert isinstance(
            model_field(InvigilatorAssignment, name),
            expected_type,
        )


class TestInvigilatorAssignmentFieldMetadata:
    def test_seating_plan_uses_cascade(self):
        assert (
            model_field(
                InvigilatorAssignment,
                "seating_plan",
            ).remote_field.on_delete
            is models.CASCADE
        )

    def test_seating_plan_related_name(self):
        assert (
            model_field(
                InvigilatorAssignment,
                "seating_plan",
            ).remote_field.related_name
            == "invigilator_assignments"
        )

    def test_staff_uses_protect(self):
        assert (
            model_field(
                InvigilatorAssignment,
                "staff",
            ).remote_field.on_delete
            is models.PROTECT
        )

    def test_staff_related_name(self):
        assert (
            model_field(
                InvigilatorAssignment,
                "staff",
            ).remote_field.related_name
            == "exam_invigilation_assignments"
        )

    def test_role_max_length(self):
        assert model_field(
            InvigilatorAssignment,
            "role",
        ).max_length == 10

    def test_role_choices(self):
        assert (
            list(
                model_field(
                    InvigilatorAssignment,
                    "role",
                ).choices
            )
            == list(InvigilatorRole.choices)
        )

    def test_role_default(self):
        assert (
            model_field(
                InvigilatorAssignment,
                "role",
            ).default
            == InvigilatorRole.ASSISTANT
        )

    def test_role_is_indexed(self):
        assert model_field(
            InvigilatorAssignment,
            "role",
        ).db_index is True

    def test_assigned_at_auto_now_add(self):
        assert model_field(
            InvigilatorAssignment,
            "assigned_at",
        ).auto_now_add is True

    def test_is_active_default(self):
        assert model_field(
            InvigilatorAssignment,
            "is_active",
        ).default is True

    def test_is_active_is_indexed(self):
        assert model_field(
            InvigilatorAssignment,
            "is_active",
        ).db_index is True


class TestInvigilatorAssignmentDefaults:
    def test_role_defaults_to_assistant(self):
        assert (
            InvigilatorAssignment().role
            == InvigilatorRole.ASSISTANT
        )

    def test_is_active_defaults_to_true(self):
        assert InvigilatorAssignment().is_active is True


class TestInvigilatorAssignmentMeta:
    def test_ordering(self):
        assert InvigilatorAssignment._meta.ordering == [
            "role",
            "assigned_at",
        ]

    def test_constraint_names(self):
        assert set(constraint_map(InvigilatorAssignment)) == {
            "unique_active_invigilator_per_plan",
            "unique_active_chief_invigilator",
        }

    def test_active_invigilator_constraint_fields(self):
        constraint = constraint_map(InvigilatorAssignment)[
            "unique_active_invigilator_per_plan"
        ]

        assert isinstance(constraint, models.UniqueConstraint)
        assert tuple(constraint.fields) == (
            "seating_plan",
            "staff",
        )
        assert constraint.condition == Q(is_active=True)

    def test_active_chief_constraint_fields(self):
        constraint = constraint_map(InvigilatorAssignment)[
            "unique_active_chief_invigilator"
        ]

        assert isinstance(constraint, models.UniqueConstraint)
        assert tuple(constraint.fields) == ("seating_plan",)
        assert constraint.condition == Q(
            role=InvigilatorRole.CHIEF,
            is_active=True,
        )

    def test_index_names(self):
        assert set(index_map(InvigilatorAssignment)) == {
            "invigilator_plan_role_idx",
            "invigilator_staff_active_idx",
        }

    def test_plan_role_index(self):
        assert index_map(InvigilatorAssignment)[
            "invigilator_plan_role_idx"
        ] == (
            "seating_plan",
            "role",
        )

    def test_staff_active_index(self):
        assert index_map(InvigilatorAssignment)[
            "invigilator_staff_active_idx"
        ] == (
            "staff",
            "is_active",
        )


class TestInvigilatorAssignmentValidation:
    def test_valid_assignment_passes_clean(self):
        make_invigilator_assignment().clean()

    def test_same_school_staff_is_valid(self):
        plan = make_plan(school_id=33)
        staff = make_staff(school_id=33)

        make_invigilator_assignment(
            plan=plan,
            staff=staff,
        ).clean()

    def test_staff_from_another_school_is_invalid(self):
        plan = make_plan(school_id=33)
        staff = make_staff(school_id=88)
        assignment = make_invigilator_assignment(
            plan=plan,
            staff=staff,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert exc_info.value.message_dict["staff"] == [
            "The invigilator must belong to the same school as the seating plan."
        ]

    def test_inactive_staff_is_invalid(self):
        plan = make_plan(school_id=33)
        staff = make_staff(
            school_id=33,
            is_active=False,
        )
        assignment = make_invigilator_assignment(
            plan=plan,
            staff=staff,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert exc_info.value.message_dict["staff"] == [
            "An inactive user cannot be assigned as an invigilator."
        ]

    def test_inactive_cross_school_error_is_overwritten(self):
        plan = make_plan(school_id=33)
        staff = make_staff(
            school_id=88,
            is_active=False,
        )
        assignment = make_invigilator_assignment(
            plan=plan,
            staff=staff,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        # The model assigns the same "staff" key twice. The later inactive-user
        # validation therefore replaces the earlier school mismatch message.
        assert exc_info.value.message_dict["staff"] == [
            "An inactive user cannot be assigned as an invigilator."
        ]

    def test_staff_without_school_id_is_allowed(self):
        plan = make_plan(school_id=33)
        staff = make_staff(
            pk=1,
            school_id=None,
            is_active=True,
            label="Staff",
        )

        make_invigilator_assignment(
            plan=plan,
            staff=staff,
        ).clean()

    def test_staff_defaults_to_active(self):
        plan = make_plan(school_id=33)
        staff = User(
            pk=1,
            email="staff-default@example.com",
            first_name="Staff",
            role=User.Role.TEACHER,
            school_id=33,
            approval_status=User.ApprovalStatus.APPROVED,
        )

        assert staff.is_active is True

        make_invigilator_assignment(
            plan=plan,
            staff=staff,
        ).clean()

    def test_missing_plan_skips_staff_validation(self):
        assignment = InvigilatorAssignment(
            staff_id=1,
            role=InvigilatorRole.ASSISTANT,
        )

        assignment.clean()

    def test_missing_staff_skips_staff_validation(self):
        assignment = InvigilatorAssignment(
            seating_plan=make_plan(),
            role=InvigilatorRole.ASSISTANT,
        )

        assignment.clean()


class TestInvigilatorAssignmentString:
    def test_string_representation(self):
        plan = make_plan(
            room="Room C",
            exam_date=date(2026, 11, 7),
            start_time=time(8, 30),
        )
        staff = make_staff(label="Mr. Kato")
        assignment = make_invigilator_assignment(
            plan=plan,
            staff=staff,
            role=InvigilatorRole.CHIEF,
        )

        assert str(assignment) == (
    f"Mr. Kato (Teacher) — "
    f"{assignment.get_role_display()} "
    "(Room C — 2026-11-07 08:30)"
)

class TestInvigilatorRoleChoices:
    @pytest.mark.parametrize(
        ("value", "label"),
        InvigilatorRole.choices,
    )
    def test_role_display(self, value, label):
        assignment = make_invigilator_assignment(role=value)

        assert assignment.get_role_display() == label