"""
Enterprise model tests for PerformanceSnapshot.

Save as:
    reports/tests/test_performance_history.py

Run:
    pytest reports/tests/test_performance_history.py -q
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import StudentProfile, User
from academics.models import AcademicTerm
from reports.constants import PerformanceSnapshotSource
from reports.models.base import SchoolScopedModel

try:
    from reports.models.performance_history import PerformanceSnapshot
except ImportError:
    from reports.models import PerformanceSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def model_field(name):
    return PerformanceSnapshot._meta.get_field(name)


def constraint_by_name(name):
    return next(
        item
        for item in PerformanceSnapshot._meta.constraints
        if item.name == name
    )


def index_by_name(name):
    return next(
        item
        for item in PerformanceSnapshot._meta.indexes
        if item.name == name
    )


def make_user(
    *,
    pk=10,
    school_id=1,
    first_name="Administrator",
    role=User.Role.ADMIN,
):
    return User(
        pk=pk,
        email=f"user{pk}@example.com",
        first_name=first_name,
        role=role,
        school_id=school_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    )


def make_student(
    *,
    pk=20,
    school_id=1,
    student_id_number="STU-001",
    name="Alice",
):
    user = User(
        pk=pk,
        email=f"student{pk}@example.com",
        first_name=name,
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


def make_term(
    *,
    pk=30,
    school_id=1,
):
    return AcademicTerm(
        pk=pk,
        school_id=school_id,
    )


def make_snapshot(**overrides):
    values = {
        "school_id": 1,
        "student": make_student(),
        "academic_term": make_term(),
        "snapshot_source": PerformanceSnapshotSource.REPORT_CARD,
        "grading_policy_version": "policy-v1",
        "gpa": Decimal("4.500"),
        "aggregate": Decimal("80.00"),
        "class_position": 1,
        "class_size": 40,
        "subject_positions": {
            "MATH": 1,
            "ENG": 3,
        },
        "class_average": Decimal("65.00"),
        "school_average": Decimal("62.00"),
        "performance_summary": {
            "subjects_passed": 8,
        },
        "computed_by": make_user(),
        "computation_reference": "JOB-001",
    }
    values.update(overrides)
    return PerformanceSnapshot(**values)


# ---------------------------------------------------------------------------
# Inheritance and manager
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotInheritance:
    def test_is_django_model(self):
        assert issubclass(PerformanceSnapshot, models.Model)

    def test_inherits_school_scoped_model(self):
        assert issubclass(
            PerformanceSnapshot,
            SchoolScopedModel,
        )

    def test_model_is_concrete(self):
        assert PerformanceSnapshot._meta.abstract is False

    def test_manager_supports_for_school(self):
        assert hasattr(
            PerformanceSnapshot.objects,
            "for_school",
        )


# ---------------------------------------------------------------------------
# Meta configuration
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotMeta:
    def test_ordering(self):
        assert PerformanceSnapshot._meta.ordering == [
            "-computed_at",
            "-id",
        ]

    @pytest.mark.parametrize(
        "name",
        [
            "performance_snapshot_gpa_nonnegative",
            "performance_snapshot_aggregate_nonnegative",
            "performance_snapshot_class_average_nonnegative",
            "performance_snapshot_school_average_nonnegative",
            "performance_snapshot_position_positive",
            "performance_snapshot_class_size_positive",
            "performance_snapshot_position_within_class",
            "unique_student_term_snapshot_source",
            "unique_performance_computation_reference",
        ],
    )
    def test_constraint_exists(self, name):
        assert constraint_by_name(name).name == name

    def test_constraint_count(self):
        assert len(
            PerformanceSnapshot._meta.constraints
        ) == 9

    def test_snapshot_identity_unique_constraint_fields(self):
        item = constraint_by_name(
            "unique_student_term_snapshot_source"
        )

        assert tuple(item.fields) == (
            "school",
            "student",
            "academic_term",
            "snapshot_source",
        )

    def test_computation_reference_unique_constraint_fields(self):
        item = constraint_by_name(
            "unique_performance_computation_reference"
        )

        assert tuple(item.fields) == (
            "school",
            "computation_reference",
        )

    def test_computation_reference_constraint_is_conditional(self):
        item = constraint_by_name(
            "unique_performance_computation_reference"
        )

        assert item.condition == ~models.Q(
            computation_reference=""
        )

    @pytest.mark.parametrize(
        ("name", "expected_fields"),
        [
            (
                "perf_school_stu_term_idx",
                ["school", "student", "academic_term"],
            ),
            (
                "perf_school_term_src_idx",
                ["school", "academic_term", "snapshot_source"],
            ),
            (
                " perf_student_hist_idx",
                ["student", "-computed_at"],
            ),
            (
                "performance_source_date_idx",
                ["school", "snapshot_source", "-computed_at"],
            ),
        ],
    )
    def test_index_fields(self, name, expected_fields):
        assert list(
            index_by_name(name).fields
        ) == expected_fields

    def test_index_count(self):
        assert len(
            PerformanceSnapshot._meta.indexes
        ) == 4


# ---------------------------------------------------------------------------
# Foreign-key metadata
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotForeignKeys:
    def test_student_foreign_key(self):
        field = model_field("student")

        assert isinstance(field, models.ForeignKey)
        assert field.remote_field.model.__name__ == "StudentProfile"
        assert field.remote_field.on_delete is models.PROTECT
        assert (
            field.remote_field.related_name
            == "performance_snapshots"
        )

    def test_academic_term_foreign_key(self):
        field = model_field("academic_term")

        assert isinstance(field, models.ForeignKey)
        assert field.remote_field.model.__name__ == "AcademicTerm"
        assert field.remote_field.on_delete is models.PROTECT
        assert (
            field.remote_field.related_name
            == "performance_snapshots"
        )

    def test_computed_by_foreign_key(self):
        field = model_field("computed_by")

        assert isinstance(field, models.ForeignKey)
        assert field.remote_field.model.__name__ == "User"
        assert field.remote_field.on_delete is models.SET_NULL
        assert field.null is True
        assert field.blank is True
        assert (
            field.remote_field.related_name
            == "computed_performance_snapshots"
        )

    @pytest.mark.parametrize(
        "field_name",
        ["student", "academic_term"],
    )
    def test_required_foreign_keys_are_not_nullable(
        self,
        field_name,
    ):
        assert model_field(field_name).null is False


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotFieldMetadata:
    def test_snapshot_source_metadata(self):
        field = model_field("snapshot_source")

        assert isinstance(field, models.CharField)
        assert field.max_length == 30
        assert tuple(field.choices) == tuple(
            PerformanceSnapshotSource.choices
        )
        assert field.db_index is True

    def test_grading_policy_version_metadata(self):
        field = model_field("grading_policy_version")

        assert isinstance(field, models.CharField)
        assert field.max_length == 100
        assert field.blank is True
        assert field.get_default() == ""

    @pytest.mark.parametrize(
        ("field_name", "max_digits", "decimal_places"),
        [
            ("gpa", 6, 3),
            ("aggregate", 8, 2),
            ("class_average", 8, 2),
            ("school_average", 8, 2),
        ],
    )
    def test_decimal_field_configuration(
        self,
        field_name,
        max_digits,
        decimal_places,
    ):
        field = model_field(field_name)

        assert isinstance(field, models.DecimalField)
        assert field.max_digits == max_digits
        assert field.decimal_places == decimal_places
        assert field.null is True
        assert field.blank is True

    @pytest.mark.parametrize(
        "field_name",
        ["class_position", "class_size"],
    )
    def test_positive_integer_field_configuration(
        self,
        field_name,
    ):
        field = model_field(field_name)

        assert isinstance(
            field,
            models.PositiveIntegerField,
        )
        assert field.null is True
        assert field.blank is True

    @pytest.mark.parametrize(
        "field_name",
        ["subject_positions", "performance_summary"],
    )
    def test_json_object_fields(self, field_name):
        field = model_field(field_name)

        assert isinstance(field, models.JSONField)
        assert field.default is dict
        assert field.blank is True

    def test_computation_reference_metadata(self):
        field = model_field("computation_reference")

        assert isinstance(field, models.CharField)
        assert field.max_length == 100
        assert field.blank is True
        assert field.get_default() == ""
        assert field.db_index is True

    def test_computed_at_metadata(self):
        field = model_field("computed_at")

        assert isinstance(field, models.DateTimeField)
        assert field.auto_now_add is True
        assert field.db_index is True


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotDefaults:
    def test_grading_policy_version_default(self):
        assert (
            PerformanceSnapshot().grading_policy_version
            == ""
        )

    def test_subject_positions_default_is_new_dict(self):
        first = PerformanceSnapshot()
        second = PerformanceSnapshot()

        assert first.subject_positions == {}
        assert second.subject_positions == {}
        assert (
            first.subject_positions
            is not second.subject_positions
        )

    def test_performance_summary_default_is_new_dict(self):
        first = PerformanceSnapshot()
        second = PerformanceSnapshot()

        assert first.performance_summary == {}
        assert second.performance_summary == {}
        assert (
            first.performance_summary
            is not second.performance_summary
        )

    def test_computation_reference_default(self):
        assert (
            PerformanceSnapshot().computation_reference
            == ""
        )

    @pytest.mark.parametrize(
        "field_name",
        [
            "gpa",
            "aggregate",
            "class_position",
            "class_size",
            "class_average",
            "school_average",
            "computed_by",
        ],
    )
    def test_optional_fields_default_to_none(
        self,
        field_name,
    ):
        assert (
            getattr(
                PerformanceSnapshot(),
                field_name,
            )
            is None
        )


# ---------------------------------------------------------------------------
# Snapshot source choices
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotSourceChoices:
    @pytest.mark.parametrize(
        ("value", "label"),
        PerformanceSnapshotSource.choices,
    )
    def test_display_value(self, value, label):
        snapshot = make_snapshot(
            snapshot_source=value
        )

        assert (
            snapshot.get_snapshot_source_display()
            == label
        )

    def test_official_document_constant_value(self):
        assert (
            PerformanceSnapshotSource.OFFICAL_DOCUMENT
            == "OFFICIAL_DOCUMENT"
        )

    def test_report_card_constant_value(self):
        assert (
            PerformanceSnapshotSource.REPORT_CARD
            == "REPORT_CARD"
        )

    def test_result_slip_constant_value(self):
        assert (
            PerformanceSnapshotSource.RESULT_SLIP
            == "RESULT_SLIP"
        )

    def test_transcript_constant_value(self):
        assert (
            PerformanceSnapshotSource.TRANSCRIPT
            == "TRANSCRIPT"
        )

    def test_analytics_job_constant_value(self):
        assert (
            PerformanceSnapshotSource.ANALYTICS_JOB
            == "ANALYTICS_JOB"
        )

    def test_manual_constant_value(self):
        assert (
            PerformanceSnapshotSource.MANUAL
            == "MANUAL"
        )


# ---------------------------------------------------------------------------
# Valid states
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotValidStates:
    def test_complete_snapshot_is_valid(self):
        make_snapshot().clean()

    def test_all_optional_metrics_can_be_none(self):
        snapshot = make_snapshot(
            gpa=None,
            aggregate=None,
            class_position=None,
            class_size=None,
            class_average=None,
            school_average=None,
            computed_by=None,
        )

        snapshot.clean()

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("gpa", Decimal("0.000")),
            ("aggregate", Decimal("0.00")),
            ("class_average", Decimal("0.00")),
            ("school_average", Decimal("0.00")),
            ("class_position", 1),
            ("class_size", 1),
        ],
    )
    def test_boundary_values_are_valid(
        self,
        field_name,
        value,
    ):
        snapshot = make_snapshot(
            **{field_name: value}
        )

        snapshot.clean()

    def test_position_equal_to_class_size_is_valid(self):
        snapshot = make_snapshot(
            class_position=40,
            class_size=40,
        )

        snapshot.clean()

    def test_empty_subject_positions_is_valid(self):
        make_snapshot(
            subject_positions={}
        ).clean()

    def test_empty_performance_summary_is_valid(self):
        make_snapshot(
            performance_summary={}
        ).clean()

    def test_student_without_school_id_is_allowed(self):
        student = make_student(
            school_id=None,
        )
        snapshot = make_snapshot(
            school_id=1,
            student=student,
        )

        snapshot.clean()

    def test_term_without_school_id_is_allowed(self):
        term = make_term(
            school_id=None,
        )
        snapshot = make_snapshot(
            school_id=1,
            academic_term=term,
        )

        snapshot.clean()

    def test_snapshot_without_school_id_skips_school_checks(self):
        snapshot = make_snapshot(
            school_id=None,
            student=make_student(
                school_id=2,
            ),
            academic_term=make_term(
                school_id=3,
            ),
        )

        snapshot.clean()


# ---------------------------------------------------------------------------
# School consistency validation
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotSchoolValidation:
    def test_student_must_belong_to_snapshot_school(self):
        snapshot = make_snapshot(
            school_id=1,
            student=make_student(
                school_id=2,
            ),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict == {
            "student": [
                "The student must belong to the same school as the "
                "performance snapshot."
            ]
        }

    def test_term_must_belong_to_snapshot_school(self):
        snapshot = make_snapshot(
            school_id=1,
            academic_term=make_term(
                school_id=2,
            ),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict == {
            "academic_term": [
                "The academic term must belong to the same school as the "
                "performance snapshot."
            ]
        }

    def test_student_and_term_school_errors_are_collected(self):
        snapshot = make_snapshot(
            school_id=1,
            student=make_student(
                school_id=2,
            ),
            academic_term=make_term(
                school_id=3,
            ),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert set(
            exc_info.value.message_dict
        ) == {
            "student",
            "academic_term",
        }


# ---------------------------------------------------------------------------
# Numeric validation
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotNumericValidation:
    @pytest.mark.parametrize(
        ("field_name", "value", "message"),
        [
            (
                "gpa",
                Decimal("-0.001"),
                "GPA cannot be negative.",
            ),
            (
                "aggregate",
                Decimal("-0.01"),
                "Aggregate cannot be negative.",
            ),
            (
                "class_average",
                Decimal("-0.01"),
                "Class average cannot be negative.",
            ),
            (
                "school_average",
                Decimal("-0.01"),
                "School average cannot be negative.",
            ),
        ],
    )
    def test_negative_decimal_metric_is_invalid(
        self,
        field_name,
        value,
        message,
    ):
        values = {field_name: value}

        # Keep class_position out of the comparison when testing an invalid
        # class_size. Otherwise the model correctly reports a second error
        # because the default position (1) is greater than size 0 or -1.
        if field_name == "class_size":
            values["class_position"] = None

        snapshot = make_snapshot(**values)

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict == {
            field_name: [message]
        }

    @pytest.mark.parametrize(
        ("field_name", "value", "message"),
        [
            (
                "class_position",
                0,
                "Class position must be at least 1.",
            ),
            (
                "class_position",
                -1,
                "Class position must be at least 1.",
            ),
            (
                "class_size",
                0,
                "Class size must be at least 1.",
            ),
            (
                "class_size",
                -1,
                "Class size must be at least 1.",
            ),
        ],
    )
    def test_invalid_position_or_size(
        self,
        field_name,
        value,
        message,
    ):
        if field_name == "class_size":
            snapshot = make_snapshot(
                class_position=None,
                class_size=value,
            )
        else:
            snapshot = make_snapshot(
                **{field_name: value}
            )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict == {
            field_name: [message]
        }

    def test_position_cannot_exceed_class_size(self):
        snapshot = make_snapshot(
            class_position=41,
            class_size=40,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict == {
            "class_position": [
                "Class position cannot be greater than class size."
            ]
        }

    def test_all_numeric_errors_are_collected(self):
        snapshot = make_snapshot(
            gpa=Decimal("-1.000"),
            aggregate=Decimal("-1.00"),
            class_average=Decimal("-1.00"),
            school_average=Decimal("-1.00"),
            class_position=0,
            class_size=0,
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert set(
            exc_info.value.message_dict
        ) == {
            "gpa",
            "aggregate",
            "class_average",
            "school_average",
            "class_position",
            "class_size",
        }


# ---------------------------------------------------------------------------
# subject_positions validation
# ---------------------------------------------------------------------------

class TestSubjectPositionsValidation:
    @pytest.mark.parametrize(
        "value",
        [
            [],
            (),
            "MATH",
            1,
            True,
            None,
        ],
    )
    def test_subject_positions_must_be_dict(self, value):
        snapshot = make_snapshot(
            subject_positions=value
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict == {
            "subject_positions": [
                "Subject positions must be stored as a JSON object."
            ]
        }

    @pytest.mark.parametrize(
        "key",
        [
            "",
            " ",
            "   ",
            123,
            None,
            False,
        ],
    )
    def test_subject_code_must_be_non_empty_string(
        self,
        key,
    ):
        snapshot = make_snapshot(
            subject_positions={key: 1}
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        message = exc_info.value.message_dict[
            "subject_positions"
        ][0]

        assert message.startswith(
            "Invalid subject positions:"
        )
        assert (
            "Subject code must be a non-empty string."
            in message
        )

    @pytest.mark.parametrize(
        "position",
        [
            0,
            -1,
            1.5,
            Decimal("1"),
            "1",
            None,
            True,
            False,
            [],
            {},
        ],
    )
    def test_subject_position_must_be_positive_integer(
        self,
        position,
    ):
        snapshot = make_snapshot(
            subject_positions={
                "MATH": position,
            }
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        message = exc_info.value.message_dict[
            "subject_positions"
        ][0]

        assert (
            "Subject position must be a positive integer."
            in message
        )

    @pytest.mark.parametrize(
        "position",
        [1, 2, 100],
    )
    def test_positive_integer_subject_position_is_valid(
        self,
        position,
    ):
        make_snapshot(
            subject_positions={
                "MATH": position,
            }
        ).clean()

    def test_multiple_invalid_subject_positions_are_reported(self):
        snapshot = make_snapshot(
            subject_positions={
                "": 1,
                "MATH": 0,
                "ENG": True,
            }
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        message = exc_info.value.message_dict[
            "subject_positions"
        ][0]

        assert (
            "Subject code must be a non-empty string."
            in message
        )
        assert (
            "Subject position must be a positive integer."
            in message
        )


# ---------------------------------------------------------------------------
# performance_summary validation
# ---------------------------------------------------------------------------

class TestPerformanceSummaryValidation:
    @pytest.mark.parametrize(
        "value",
        [
            [],
            (),
            "summary",
            1,
            True,
            None,
        ],
    )
    def test_performance_summary_must_be_dict(self, value):
        snapshot = make_snapshot(
            performance_summary=value
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict == {
            "performance_summary": [
                "Performance summary must be stored as a JSON object."
            ]
        }

    @pytest.mark.parametrize(
        "value",
        [
            {},
            {"subjects_passed": 8},
            {"nested": {"value": 1}},
            {"items": [1, 2, 3]},
        ],
    )
    def test_dictionary_performance_summary_is_valid(
        self,
        value,
    ):
        make_snapshot(
            performance_summary=value
        ).clean()


# ---------------------------------------------------------------------------
# Error aggregation
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotErrorAggregation:
    def test_errors_from_multiple_sections_are_collected(self):
        snapshot = make_snapshot(
            school_id=1,
            student=make_student(
                school_id=2,
            ),
            academic_term=make_term(
                school_id=3,
            ),
            gpa=Decimal("-1.000"),
            aggregate=Decimal("-1.00"),
            class_position=0,
            class_size=0,
            subject_positions=[],
            performance_summary=[],
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.clean()

        assert set(
            exc_info.value.message_dict
        ) == {
            "student",
            "academic_term",
            "gpa",
            "aggregate",
            "class_position",
            "class_size",
            "subject_positions",
            "performance_summary",
        }


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotImmutability:
    def test_save_rejects_instance_with_primary_key(self):
        snapshot = make_snapshot()
        snapshot.pk = 99

        with pytest.raises(
            ValidationError,
            match=(
                "Performance snapshots are immutable "
                "and cannot be modified."
            ),
        ):
            snapshot.save()

    def test_save_runs_full_clean_for_new_instance(self, monkeypatch):
        snapshot = make_snapshot()
        expected_error = ValidationError({
            "gpa": ["GPA cannot be negative."]
        })

        def fake_full_clean(*args, **kwargs):
            raise expected_error

        monkeypatch.setattr(snapshot, "full_clean", fake_full_clean)

        with pytest.raises(ValidationError) as exc_info:
            snapshot.save()

        assert exc_info.value.message_dict == {
            "gpa": ["GPA cannot be negative."]
        }

    def test_delete_is_always_rejected(self):
        snapshot = make_snapshot()

        with pytest.raises(
            ValidationError,
            match=(
                "Performance snapshots are historical "
                "records and cannot be deleted."
            ),
        ):
            snapshot.delete()

    def test_delete_rejects_instance_with_primary_key(self):
        snapshot = make_snapshot()
        snapshot.pk = 99

        with pytest.raises(
            ValidationError,
            match=(
                "Performance snapshots are historical "
                "records and cannot be deleted."
            ),
        ):
            snapshot.delete()


# ---------------------------------------------------------------------------
# String representation
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotString:
    @pytest.mark.parametrize(
        ("source", "label"),
        PerformanceSnapshotSource.choices,
    )
    def test_string_representation(
        self,
        source,
        label,
        monkeypatch,
    ):
        monkeypatch.setattr(
            AcademicTerm,
            "__str__",
            lambda self: "Term 1 — 2026 — ASMS",
        )
        student = make_student(
            student_id_number="STU-777",
            name="Alice",
        )
        term = make_term()
        snapshot = make_snapshot(
            student=student,
            academic_term=term,
            snapshot_source=source,
        )

        assert str(snapshot) == (
            f"{student} — {term} — {label}"
        )

    def test_string_contains_student_string(self, monkeypatch):
        monkeypatch.setattr(
            AcademicTerm,
            "__str__",
            lambda self: "Term 1 — 2026 — ASMS",
        )
        student = make_student(
            student_id_number="ASMS-001",
            name="Joseph",
        )
        snapshot = make_snapshot(
            student=student,
        )

        assert str(student) in str(snapshot)

    def test_string_contains_term_string(self, monkeypatch):
        monkeypatch.setattr(
            AcademicTerm,
            "__str__",
            lambda self: "Term 1 — 2026 — ASMS",
        )
        term = make_term()
        snapshot = make_snapshot(
            academic_term=term,
        )

        assert str(term) in str(snapshot)


# ---------------------------------------------------------------------------
# full_clean field-level behavior
# ---------------------------------------------------------------------------

class TestPerformanceSnapshotFullClean:
    def _excluded_relations(self):
        return [
            "school",
            "student",
            "academic_term",
            "computed_by",
        ]

    def test_snapshot_source_is_required(self):
        snapshot = make_snapshot(
            snapshot_source="",
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.full_clean(
                exclude=self._excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "snapshot_source"
            in exc_info.value.message_dict
        )

    def test_invalid_snapshot_source_is_rejected(self):
        snapshot = make_snapshot(
            snapshot_source="INVALID",
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.full_clean(
                exclude=self._excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "snapshot_source"
            in exc_info.value.message_dict
        )

    def test_gpa_exceeding_max_digits_is_rejected(self):
        snapshot = make_snapshot(
            gpa=Decimal("1234.567"),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.full_clean(
                exclude=self._excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert "gpa" in exc_info.value.message_dict

    def test_aggregate_exceeding_max_digits_is_rejected(self):
        snapshot = make_snapshot(
            aggregate=Decimal("1234567.89"),
        )

        with pytest.raises(
            ValidationError
        ) as exc_info:
            snapshot.full_clean(
                exclude=self._excluded_relations(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "aggregate"
            in exc_info.value.message_dict
        )