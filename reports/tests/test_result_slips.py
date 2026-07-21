"""
Enterprise model tests for ResultSlip.

Save as:
    reports/tests/test_result_slips.py

Run:
    pytest reports/tests/test_result_slips.py -q
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from accounts.models import StudentProfile, User
from academics.models import AcademicTerm, AcademicYear, Classroom
from reports.constants import ResultSlipOutcome
from reports.models.base import (
    AbstractGeneratedArtifact,
    AuditableModel,
    SchoolScopedModel,
    VersionedModel,
)

try:
    from reports.models.result_slips import ResultSlip
except ImportError:
    from reports.models import ResultSlip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def model_field(name):
    return ResultSlip._meta.get_field(name)


def constraint_by_name(name):
    return next(
        item
        for item in ResultSlip._meta.constraints
        if item.name == name
    )


def index_by_name(name):
    return next(
        item
        for item in ResultSlip._meta.indexes
        if item.name == name
    )


def make_user(
    *,
    pk=10,
    school_id=1,
    first_name="Alice",
):
    return User(
        pk=pk,
        email=f"user{pk}@example.com",
        first_name=first_name,
        role=User.Role.STUDENT,
        school_id=school_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    )


def make_student(
    *,
    pk=20,
    school_id=1,
    first_name="Alice",
    student_id_number="STU-001",
):
    return StudentProfile(
        pk=pk,
        user=make_user(
            pk=pk,
            school_id=school_id,
            first_name=first_name,
        ),
        school_id=school_id,
        student_id_number=student_id_number,
        is_active_student=True,
    )


def make_year(
    *,
    pk=30,
    school_id=1,
):
    return AcademicYear(
        pk=pk,
        school_id=school_id,
    )


def make_term(
    *,
    pk=40,
    school_id=1,
    academic_year_id=30,
):
    return AcademicTerm(
        pk=pk,
        school_id=school_id,
        academic_year_id=academic_year_id,
    )


def make_classroom(
    *,
    pk=50,
    school_id=1,
):
    return Classroom(
        pk=pk,
        school_id=school_id,
    )


def first_outcome_value():
    return ResultSlipOutcome.choices[0][0]


def make_result_slip(**overrides):
    year = overrides.pop(
        "academic_year",
        make_year(),
    )
    term = overrides.pop(
        "term",
        make_term(
            academic_year_id=year.pk,
            school_id=year.school_id,
        ),
    )

    values = {
        "school_id": 1,
        "student": make_student(),
        "academic_year": year,
        "term": term,
        "classroom": make_classroom(),
        "subjects_snapshot": [
            {
                "subject_id": 1,
                "subject_name": "Mathematics",
                "subject_code": "MATH",
                "marks": "78.00",
                "grade": "A",
                "remarks": "Excellent",
            }
        ],
        "aggregate_or_gpa": Decimal("78.00"),
        "position": 1,
        "class_average": Decimal("65.00"),
        "pass_fail_status": first_outcome_value(),
        "verification_code": "VERIFY-RESULT-001",
        "version": 1,
        "root_id": "root-result-slip-001",
        "is_latest": True,
    }
    values.update(overrides)
    return ResultSlip(**values)


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------

class TestResultSlipInheritance:
    def test_is_django_model(self):
        assert issubclass(ResultSlip, models.Model)

    def test_inherits_generated_artifact(self):
        assert issubclass(
            ResultSlip,
            AbstractGeneratedArtifact,
        )

    def test_inherits_versioned_model(self):
        assert issubclass(
            ResultSlip,
            VersionedModel,
        )

    def test_inherits_school_scoped_model(self):
        assert issubclass(
            ResultSlip,
            SchoolScopedModel,
        )

    def test_inherits_auditable_model(self):
        assert issubclass(
            ResultSlip,
            AuditableModel,
        )

    def test_model_is_concrete(self):
        assert ResultSlip._meta.abstract is False


# ---------------------------------------------------------------------------
# Meta configuration
# ---------------------------------------------------------------------------

class TestResultSlipMeta:
    def test_ordering(self):
        assert ResultSlip._meta.ordering == [
            "-created_at",
            "-pk",
        ]

    def test_constraint_count(self):
        assert len(ResultSlip._meta.constraints) == 6

    @pytest.mark.parametrize(
        "name",
        [
            "rs_aggregate_nonnegative",
            "rs_class_avg_nonnegative",
            "rs_position_gte_1",
            "rs_version_gte_1",
            "uniq_rs_chain_version",
            "uniq_latest_rs",
        ],
    )
    def test_constraint_exists(self, name):
        assert constraint_by_name(name).name == name

    def test_chain_version_unique_constraint_fields(self):
        constraint = constraint_by_name(
            "uniq_rs_chain_version"
        )

        assert tuple(constraint.fields) == (
            "school",
            "root_id",
            "version",
        )

    def test_latest_unique_constraint_fields(self):
        constraint = constraint_by_name(
            "uniq_latest_rs"
        )

        assert tuple(constraint.fields) == (
            "school",
            "root_id",
        )

    def test_latest_constraint_is_conditional(self):
        constraint = constraint_by_name(
            "uniq_latest_rs"
        )

        assert constraint.condition == Q(
            is_latest=True
        )

    def test_index_count(self):
        assert len(ResultSlip._meta.indexes) == 6

    @pytest.mark.parametrize(
        ("name", "expected_fields"),
        [
            (
                "rs_student_term_idx",
                ["school", "student", "term"],
            ),
            (
                "rs_year_term_idx",
                ["school", "academic_year", "term"],
            ),
            (
                "rs_class_term_idx",
                ["school", "classroom", "term"],
            ),
            (
                "rs_outcome_idx",
                ["school", "pass_fail_status"],
            ),
            (
                "rs_status_time_idx",
                ["school", "status", "-created_at"],
            ),
            (
                "rs_root_version_idx",
                ["root_id", "version"],
            ),
        ],
    )
    def test_index_fields(
        self,
        name,
        expected_fields,
    ):
        assert list(
            index_by_name(name).fields
        ) == expected_fields


# ---------------------------------------------------------------------------
# Foreign-key metadata
# ---------------------------------------------------------------------------

class TestResultSlipForeignKeys:
    @pytest.mark.parametrize(
        (
            "field_name",
            "related_model_name",
            "related_name",
        ),
        [
            (
                "student",
                "StudentProfile",
                "result_slips",
            ),
            (
                "academic_year",
                "AcademicYear",
                "result_slips",
            ),
            (
                "term",
                "AcademicTerm",
                "result_slips",
            ),
            (
                "classroom",
                "Classroom",
                "result_slips",
            ),
        ],
    )
    def test_required_protected_foreign_keys(
        self,
        field_name,
        related_model_name,
        related_name,
    ):
        field = model_field(field_name)

        assert isinstance(field, models.ForeignKey)
        assert (
            field.remote_field.model.__name__
            == related_model_name
        )
        assert field.remote_field.on_delete is models.PROTECT
        assert (
            field.remote_field.related_name
            == related_name
        )
        assert field.null is False
        assert field.blank is False


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------

class TestResultSlipFieldMetadata:
    def test_subjects_snapshot_metadata(self):
        field = model_field("subjects_snapshot")

        assert isinstance(field, models.JSONField)
        assert field.default is list
        assert field.blank is True

    def test_aggregate_or_gpa_metadata(self):
        field = model_field("aggregate_or_gpa")

        assert isinstance(field, models.DecimalField)
        assert field.max_digits == 8
        assert field.decimal_places == 2
        assert field.null is True
        assert field.blank is True

    def test_position_metadata(self):
        field = model_field("position")

        assert isinstance(
            field,
            models.PositiveIntegerField,
        )
        assert field.null is True
        assert field.blank is True

    def test_class_average_metadata(self):
        field = model_field("class_average")

        assert isinstance(field, models.DecimalField)
        assert field.max_digits == 8
        assert field.decimal_places == 2
        assert field.null is True
        assert field.blank is True

    def test_pass_fail_status_metadata(self):
        field = model_field("pass_fail_status")

        assert isinstance(field, models.CharField)
        assert field.max_length == 20
        assert tuple(field.choices) == tuple(
            ResultSlipOutcome.choices
        )
        assert (
            field.get_default()
            == ResultSlipOutcome.NOT_APPLICABLE
        )
        assert field.db_index is True

    def test_verification_code_metadata(self):
        field = model_field("verification_code")

        assert isinstance(field, models.CharField)
        assert field.max_length == 64
        assert field.unique is True
        assert field.db_index is True
        assert field.null is False
        assert field.blank is False


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestResultSlipDefaults:
    def test_subjects_snapshot_default_is_empty_list(self):
        slip = ResultSlip()

        assert slip.subjects_snapshot == []

    def test_subjects_snapshot_default_is_not_shared(self):
        first = ResultSlip()
        second = ResultSlip()

        assert (
            first.subjects_snapshot
            is not second.subjects_snapshot
        )

    def test_pass_fail_status_default(self):
        slip = ResultSlip()

        assert (
            slip.pass_fail_status
            == ResultSlipOutcome.NOT_APPLICABLE
        )

    @pytest.mark.parametrize(
        "field_name",
        [
            "aggregate_or_gpa",
            "position",
            "class_average",
        ],
    )
    def test_optional_metric_defaults_to_none(
        self,
        field_name,
    ):
        assert getattr(
            ResultSlip(),
            field_name,
        ) is None


# ---------------------------------------------------------------------------
# Choice display
# ---------------------------------------------------------------------------

class TestResultSlipOutcomeChoices:
    @pytest.mark.parametrize(
        ("value", "label"),
        ResultSlipOutcome.choices,
    )
    def test_display_value(self, value, label):
        slip = make_result_slip(
            pass_fail_status=value
        )

        assert (
            slip.get_pass_fail_status_display()
            == label
        )

    def test_default_choice_is_available(self):
        values = [
            value
            for value, _label
            in ResultSlipOutcome.choices
        ]

        assert (
            ResultSlipOutcome.NOT_APPLICABLE
            in values
        )


# ---------------------------------------------------------------------------
# Valid states
# ---------------------------------------------------------------------------

class TestResultSlipValidStates:
    def test_complete_result_slip_is_valid(self):
        make_result_slip().clean()

    def test_empty_subject_snapshot_is_valid(self):
        make_result_slip(
            subjects_snapshot=[]
        ).clean()

    def test_optional_metrics_can_be_none(self):
        make_result_slip(
            aggregate_or_gpa=None,
            position=None,
            class_average=None,
        ).clean()

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            (
                "aggregate_or_gpa",
                Decimal("0.00"),
            ),
            (
                "class_average",
                Decimal("0.00"),
            ),
            (
                "position",
                1,
            ),
        ],
    )
    def test_boundary_values_are_valid(
        self,
        field_name,
        value,
    ):
        make_result_slip(
            **{field_name: value}
        ).clean()

    def test_multiple_subject_results_are_valid(self):
        slip = make_result_slip(
            subjects_snapshot=[
                {
                    "subject_name": "Mathematics",
                    "marks": "80.00",
                },
                {
                    "subject_name": "English",
                    "marks": "70.00",
                },
            ]
        )

        slip.clean()

    def test_subject_name_with_extra_fields_is_valid(self):
        slip = make_result_slip(
            subjects_snapshot=[
                {
                    "subject_name": "Physics",
                    "custom": {
                        "teacher_comment": "Good",
                    },
                }
            ]
        )

        slip.clean()

    def test_school_checks_skipped_without_school(self):
        slip = make_result_slip(
            school_id=None,
            student=make_student(
                school_id=2,
            ),
            academic_year=make_year(
                school_id=3,
            ),
            term=make_term(
                school_id=4,
                academic_year_id=30,
            ),
            classroom=make_classroom(
                school_id=5,
            ),
        )

        slip.clean()


# ---------------------------------------------------------------------------
# subjects_snapshot validation
# ---------------------------------------------------------------------------

class TestSubjectsSnapshotValidation:
    @pytest.mark.parametrize(
        "value",
        [
            {},
            (),
            "subjects",
            1,
            True,
            None,
        ],
    )
    def test_subjects_snapshot_must_be_list(
        self,
        value,
    ):
        slip = make_result_slip(
            subjects_snapshot=value
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "subjects_snapshot": [
                "The subjects snapshot must be a JSON list."
            ]
        }

    @pytest.mark.parametrize(
        "subject_result",
        [
            "Mathematics",
            1,
            True,
            None,
            [],
            (),
        ],
    )
    def test_each_subject_result_must_be_dict(
        self,
        subject_result,
    ):
        slip = make_result_slip(
            subjects_snapshot=[
                subject_result,
            ]
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "subjects_snapshot": [
                "Subject result at position 1 must be "
                "a JSON object."
            ]
        }

    @pytest.mark.parametrize(
        "subject_result",
        [
            {},
            {"subject_name": ""},
            {"subject_name": None},
            {"subject_name": False},
            {"subject_code": "MATH"},
        ],
    )
    def test_subject_name_is_required(
        self,
        subject_result,
    ):
        slip = make_result_slip(
            subjects_snapshot=[
                subject_result,
            ]
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "subjects_snapshot": [
                "Subject result at position 1 must include "
                "'subject_name'."
            ]
        }

    def test_error_reports_correct_list_position(self):
        slip = make_result_slip(
            subjects_snapshot=[
                {
                    "subject_name": "Mathematics",
                },
                {
                    "subject_code": "ENG",
                },
            ]
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "subjects_snapshot": [
                "Subject result at position 2 must include "
                "'subject_name'."
            ]
        }

    def test_validation_stops_at_first_invalid_item(self):
        slip = make_result_slip(
            subjects_snapshot=[
                "invalid-first",
                {},
            ]
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "subjects_snapshot": [
                "Subject result at position 1 must be "
                "a JSON object."
            ]
        }


# ---------------------------------------------------------------------------
# Numeric validation
# ---------------------------------------------------------------------------

class TestResultSlipNumericValidation:
    def test_negative_aggregate_or_gpa_is_invalid(self):
        slip = make_result_slip(
            aggregate_or_gpa=Decimal("-0.01")
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "aggregate_or_gpa": [
                "Aggregate, average, or GPA cannot be negative."
            ]
        }

    def test_negative_class_average_is_invalid(self):
        slip = make_result_slip(
            class_average=Decimal("-0.01")
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "class_average": [
                "Class average cannot be negative."
            ]
        }

    @pytest.mark.parametrize(
        "value",
        [0, -1],
    )
    def test_position_below_one_is_invalid(
        self,
        value,
    ):
        slip = make_result_slip(
            position=value
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "position": [
                "Student position must be at least 1."
            ]
        }

    def test_numeric_errors_are_collected(self):
        slip = make_result_slip(
            aggregate_or_gpa=Decimal("-1.00"),
            class_average=Decimal("-1.00"),
            position=0,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert set(
            exc_info.value.message_dict
        ) == {
            "aggregate_or_gpa",
            "class_average",
            "position",
        }


# ---------------------------------------------------------------------------
# Academic-year and term validation
# ---------------------------------------------------------------------------

class TestResultSlipTermValidation:
    def test_term_must_belong_to_selected_year(self):
        year = make_year(
            pk=30,
        )
        term = make_term(
            academic_year_id=999,
        )
        slip = make_result_slip(
            academic_year=year,
            term=term,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "term": [
                "The selected term does not belong to the selected "
                "academic year."
            ]
        }

    def test_matching_term_and_year_are_valid(self):
        year = make_year(
            pk=30,
        )
        term = make_term(
            academic_year_id=30,
        )

        make_result_slip(
            academic_year=year,
            term=term,
        ).clean()

    def test_term_check_skipped_without_term_id(self):
        year = make_year(
            pk=30,
        )
        term = make_term(
            pk=None,
            academic_year_id=999,
        )

        make_result_slip(
            academic_year=year,
            term=term,
        ).clean()

    def test_term_check_skipped_without_year_id(self):
        year = make_year(
            pk=None,
        )
        term = make_term(
            academic_year_id=999,
        )

        make_result_slip(
            academic_year=year,
            term=term,
        ).clean()


# ---------------------------------------------------------------------------
# School isolation validation
# ---------------------------------------------------------------------------

class TestResultSlipSchoolValidation:
    def test_student_must_belong_to_slip_school(self):
        slip = make_result_slip(
            school_id=1,
            student=make_student(
                school_id=2,
            ),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "student": [
                "The student must belong to the result slip's school."
            ]
        }

    def test_classroom_must_belong_to_slip_school(self):
        slip = make_result_slip(
            school_id=1,
            classroom=make_classroom(
                school_id=2,
            ),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "classroom": [
                "The classroom must belong to the result slip's school."
            ]
        }

    def test_year_must_belong_to_slip_school(self):
        year = make_year(
            school_id=2,
        )
        term = make_term(
            school_id=1,
            academic_year_id=year.pk,
        )
        slip = make_result_slip(
            school_id=1,
            academic_year=year,
            term=term,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "academic_year": [
                "The academic year must belong to the result slip's "
                "school."
            ]
        }

    def test_term_must_belong_to_slip_school(self):
        year = make_year(
            school_id=1,
        )
        term = make_term(
            school_id=2,
            academic_year_id=year.pk,
        )
        slip = make_result_slip(
            school_id=1,
            academic_year=year,
            term=term,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert exc_info.value.message_dict == {
            "term": [
                "The term must belong to the result slip's school."
            ]
        }

    def test_all_school_errors_are_collected(self):
        year = make_year(
            school_id=4,
        )
        term = make_term(
            school_id=5,
            academic_year_id=year.pk,
        )
        slip = make_result_slip(
            school_id=1,
            student=make_student(
                school_id=2,
            ),
            classroom=make_classroom(
                school_id=3,
            ),
            academic_year=year,
            term=term,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert set(
            exc_info.value.message_dict
        ) == {
            "student",
            "classroom",
            "academic_year",
            "term",
        }

    def test_related_object_without_school_id_is_allowed(self):
        student = make_student(
            school_id=None,
        )
        classroom = make_classroom(
            school_id=None,
        )
        year = make_year(
            school_id=None,
        )
        term = make_term(
            school_id=None,
            academic_year_id=year.pk,
        )

        make_result_slip(
            school_id=1,
            student=student,
            classroom=classroom,
            academic_year=year,
            term=term,
        ).clean()


# ---------------------------------------------------------------------------
# Combined error aggregation
# ---------------------------------------------------------------------------

class TestResultSlipErrorAggregation:
    def test_errors_from_multiple_sections_are_collected(self):
        year = make_year(
            school_id=4,
        )
        term = make_term(
            school_id=5,
            academic_year_id=999,
        )
        slip = make_result_slip(
            school_id=1,
            student=make_student(
                school_id=2,
            ),
            classroom=make_classroom(
                school_id=3,
            ),
            academic_year=year,
            term=term,
            subjects_snapshot={},
            aggregate_or_gpa=Decimal("-1.00"),
            class_average=Decimal("-1.00"),
            position=0,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.clean()

        assert set(
            exc_info.value.message_dict
        ) == {
            "subjects_snapshot",
            "aggregate_or_gpa",
            "class_average",
            "position",
            "term",
            "student",
            "classroom",
            "academic_year",
        }


# ---------------------------------------------------------------------------
# String representation
# ---------------------------------------------------------------------------

class TestResultSlipStringRepresentation:
    def test_string_representation(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            StudentProfile,
            "__str__",
            lambda self: "Alice Student",
        )
        monkeypatch.setattr(
            AcademicTerm,
            "__str__",
            lambda self: "Term One",
        )

        slip = make_result_slip(
            version=3,
        )

        assert str(slip) == (
            "Result slip: Alice Student — Term One — v3"
        )

    def test_string_contains_version(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            StudentProfile,
            "__str__",
            lambda self: "Student",
        )
        monkeypatch.setattr(
            AcademicTerm,
            "__str__",
            lambda self: "Term",
        )

        slip = make_result_slip(
            version=7,
        )

        assert str(slip).endswith("v7")

    def test_string_contains_student_and_term(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            StudentProfile,
            "__str__",
            lambda self: "Student A",
        )
        monkeypatch.setattr(
            AcademicTerm,
            "__str__",
            lambda self: "Second Term",
        )

        text = str(make_result_slip())

        assert "Student A" in text
        assert "Second Term" in text


# ---------------------------------------------------------------------------
# full_clean field validation without database queries
# ---------------------------------------------------------------------------

class TestResultSlipFullClean:
    def excluded_relations(self):
        return [
            "school",
            "student",
            "academic_year",
            "term",
            "classroom",
            "created_by",
            "updated_by",
        ]

    def test_verification_code_is_required(self):
        slip = make_result_slip(
            verification_code="",
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.full_clean(
                exclude=self.excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "verification_code"
            in exc_info.value.message_dict
        )

    def test_invalid_outcome_is_rejected(self):
        slip = make_result_slip(
            pass_fail_status="INVALID",
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.full_clean(
                exclude=self.excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "pass_fail_status"
            in exc_info.value.message_dict
        )

    def test_verification_code_over_max_length_is_rejected(self):
        slip = make_result_slip(
            verification_code="X" * 65,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.full_clean(
                exclude=self.excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "verification_code"
            in exc_info.value.message_dict
        )

    def test_aggregate_exceeding_max_digits_is_rejected(self):
        slip = make_result_slip(
            aggregate_or_gpa=Decimal("1234567.89"),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.full_clean(
                exclude=self.excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "aggregate_or_gpa"
            in exc_info.value.message_dict
        )

    def test_class_average_exceeding_max_digits_is_rejected(self):
        slip = make_result_slip(
            class_average=Decimal("1234567.89"),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            slip.full_clean(
                exclude=self.excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "class_average"
            in exc_info.value.message_dict
        )