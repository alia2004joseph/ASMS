"""
Enterprise-grade tests for TranscriptGPASnapshot.

Save as:
    reports/tests/test_transcript_gpa_snapshot.py

Run:
    pytest reports/tests/test_transcript_gpa_snapshot.py -q
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from academics.models import AcademicTerm
from reports.models.base import AbstractGeneratedArtifact, SchoolScopedModel, VersionedModel


from reports.models.transcripts import TranscriptGPASnapshot, TranscriptRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def field(name):
    return TranscriptGPASnapshot._meta.get_field(name)


def constraint(name):
    return next(
        item
        for item in TranscriptGPASnapshot._meta.constraints
        if item.name == name
    )


def index(name):
    return next(
        item
        for item in TranscriptGPASnapshot._meta.indexes
        if item.name == name
    )


def make_transcript(
    *,
    pk=100,
    school_id=1,
    version=1,
    root_id="transcript-root-001",
):
    return TranscriptRecord(
        pk=pk,
        school_id=school_id,
        student_name_snapshot="Alice Student",
        verification_code=f"VERIFY-{pk}",
        version=version,
        root_id=root_id,
        is_latest=True,
    )


def make_term(
    *,
    pk=200,
    school_id=1,
):
    return AcademicTerm(
        pk=pk,
        school_id=school_id,
    )


def make_snapshot(**overrides):
    values = {
        "pk": None,
        "transcript": make_transcript(),
        "academic_term": make_term(),
        "sequence_number": 1,
        "academic_year_snapshot": "2025/2026",
        "term_name_snapshot": "Term One",
        "term_gpa": Decimal("3.500"),
        "cumulative_gpa": Decimal("3.750"),
        "credits_attempted": Decimal("20.00"),
        "credits_earned": Decimal("18.00"),
        "term_aggregate": Decimal("75.00"),
        "results_snapshot": [
            {
                "subject_code": "MATH",
                "subject_name": "Mathematics",
                "grade": "A",
                "score": "80.00",
                "credits": "3.00",
                "remarks": "Excellent",
            }
        ],
    }
    values.update(overrides)
    return TranscriptGPASnapshot(**values)


def assert_message(exc_info, key, expected):
    assert exc_info.value.message_dict[key] == [expected]


# ---------------------------------------------------------------------------
# Inheritance and model identity
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotInheritance:
    def test_is_django_model(self):
        assert issubclass(TranscriptGPASnapshot, models.Model)

    def test_model_is_concrete(self):
        assert TranscriptGPASnapshot._meta.abstract is False

    def test_does_not_inherit_generated_artifact(self):
        assert not issubclass(
            TranscriptGPASnapshot,
            AbstractGeneratedArtifact,
        )

    def test_does_not_inherit_versioned_model(self):
        assert not issubclass(
            TranscriptGPASnapshot,
            VersionedModel,
        )

    def test_does_not_inherit_school_scoped_model(self):
        assert not issubclass(
            TranscriptGPASnapshot,
            SchoolScopedModel,
        )


# ---------------------------------------------------------------------------
# Meta options
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotMeta:
    def test_ordering(self):
        assert TranscriptGPASnapshot._meta.ordering == [
            "sequence_number",
            "id",
        ]

    def test_constraint_count(self):
        assert len(TranscriptGPASnapshot._meta.constraints) == 9

    @pytest.mark.parametrize(
        "name",
        [
            "transcript_snapshot_sequence_gte_1",
            "transcript_snapshot_term_gpa_nonnegative",
            "transcript_snapshot_cumulative_gpa_nonnegative",
            "transcript_snapshot_attempted_nonnegative",
            "transcript_snapshot_earned_nonnegative",
            "transcript_snapshot_earned_lte_attempted",
            "transcript_snapshot_aggregate_nonnegative",
            "unique_term_per_transcript",
            "unique_transcript_snapshot_sequence",
        ],
    )
    def test_constraint_exists(self, name):
        assert constraint(name).name == name

    def test_unique_term_constraint_fields(self):
        item = constraint("unique_term_per_transcript")

        assert tuple(item.fields) == (
            "transcript",
            "academic_term",
        )

    def test_unique_sequence_constraint_fields(self):
        item = constraint(
            "unique_transcript_snapshot_sequence"
        )

        assert tuple(item.fields) == (
            "transcript",
            "sequence_number",
        )

    def test_index_count(self):
        assert len(TranscriptGPASnapshot._meta.indexes) == 2

    @pytest.mark.parametrize(
        ("name", "expected_fields"),
        [
            (
                "transcript_snapshot_term_idx",
                ["transcript", "academic_term"],
            ),
            (
                "transcript_snapshot_order_idx",
                ["transcript", "sequence_number"],
            ),
        ],
    )
    def test_index_fields(self, name, expected_fields):
        assert list(index(name).fields) == expected_fields


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotFields:
    def test_transcript_foreign_key(self):
        item = field("transcript")

        assert isinstance(item, models.ForeignKey)
        assert item.remote_field.model is TranscriptRecord
        assert item.remote_field.on_delete is models.CASCADE
        assert item.remote_field.related_name == "gpa_snapshots"
        assert item.null is False
        assert item.blank is False

    def test_academic_term_foreign_key(self):
        item = field("academic_term")

        assert isinstance(item, models.ForeignKey)
        assert item.remote_field.model is AcademicTerm
        assert item.remote_field.on_delete is models.PROTECT
        assert (
            item.remote_field.related_name
            == "transcript_gpa_snapshots"
        )
        assert item.null is False
        assert item.blank is False

    def test_sequence_number_metadata(self):
        item = field("sequence_number")

        assert isinstance(
            item,
            models.PositiveIntegerField,
        )
        assert item.null is False
        assert item.blank is False

    @pytest.mark.parametrize(
        ("field_name", "max_length"),
        [
            ("academic_year_snapshot", 100),
            ("term_name_snapshot", 100),
        ],
    )
    def test_snapshot_label_metadata(
        self,
        field_name,
        max_length,
    ):
        item = field(field_name)

        assert isinstance(item, models.CharField)
        assert item.max_length == max_length
        assert item.null is False
        assert item.blank is False

    @pytest.mark.parametrize(
        ("field_name", "max_digits", "decimal_places"),
        [
            ("term_gpa", 6, 3),
            ("cumulative_gpa", 6, 3),
            ("credits_attempted", 10, 2),
            ("credits_earned", 10, 2),
            ("term_aggregate", 10, 2),
        ],
    )
    def test_decimal_field_metadata(
        self,
        field_name,
        max_digits,
        decimal_places,
    ):
        item = field(field_name)

        assert isinstance(item, models.DecimalField)
        assert item.max_digits == max_digits
        assert item.decimal_places == decimal_places

    @pytest.mark.parametrize(
        "field_name",
        [
            "term_gpa",
            "cumulative_gpa",
            "term_aggregate",
        ],
    )
    def test_optional_decimal_fields(
        self,
        field_name,
    ):
        item = field(field_name)

        assert item.null is True
        assert item.blank is True

    @pytest.mark.parametrize(
        "field_name",
        [
            "credits_attempted",
            "credits_earned",
        ],
    )
    def test_credit_defaults(self, field_name):
        item = field(field_name)

        assert item.default == 0
        assert item.null is False

    def test_results_snapshot_metadata(self):
        item = field("results_snapshot")

        assert isinstance(item, models.JSONField)
        assert item.default is list
        assert item.blank is True

    def test_computed_at_metadata(self):
        item = field("computed_at")

        assert isinstance(item, models.DateTimeField)
        assert item.auto_now_add is True
        assert item.db_index is True


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotDefaults:
    def test_results_snapshot_defaults_to_empty_list(self):
        assert TranscriptGPASnapshot().results_snapshot == []

    def test_results_snapshot_default_not_shared(self):
        first = TranscriptGPASnapshot()
        second = TranscriptGPASnapshot()

        assert first.results_snapshot is not second.results_snapshot

    @pytest.mark.parametrize(
        "field_name",
        [
            "credits_attempted",
            "credits_earned",
        ],
    )
    def test_credit_fields_default_to_zero(
        self,
        field_name,
    ):
        assert getattr(
            TranscriptGPASnapshot(),
            field_name,
        ) == 0

    @pytest.mark.parametrize(
        "field_name",
        [
            "term_gpa",
            "cumulative_gpa",
            "term_aggregate",
        ],
    )
    def test_optional_metrics_default_none(
        self,
        field_name,
    ):
        assert getattr(
            TranscriptGPASnapshot(),
            field_name,
        ) is None


# ---------------------------------------------------------------------------
# Valid states
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotValidStates:
    def test_complete_snapshot_is_valid(self):
        make_snapshot().clean()

    def test_optional_metrics_can_be_none(self):
        make_snapshot(
            term_gpa=None,
            cumulative_gpa=None,
            term_aggregate=None,
        ).clean()

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("term_gpa", Decimal("0.000")),
            ("cumulative_gpa", Decimal("0.000")),
            ("credits_attempted", Decimal("0.00")),
            ("credits_earned", Decimal("0.00")),
            ("term_aggregate", Decimal("0.00")),
        ],
    )
    def test_zero_boundary_is_valid(
        self,
        field_name,
        value,
    ):
        kwargs = {field_name: value}

        if field_name == "credits_attempted":
            kwargs["credits_earned"] = Decimal("0.00")

        make_snapshot(**kwargs).clean()

    def test_credits_earned_equal_attempted_is_valid(self):
        make_snapshot(
            credits_attempted=Decimal("20.00"),
            credits_earned=Decimal("20.00"),
        ).clean()

    def test_empty_results_snapshot_is_valid(self):
        make_snapshot(
            results_snapshot=[]
        ).clean()

    def test_subject_code_only_is_valid(self):
        make_snapshot(
            results_snapshot=[
                {"subject_code": "MATH"}
            ]
        ).clean()

    def test_subject_name_only_is_valid(self):
        make_snapshot(
            results_snapshot=[
                {"subject_name": "Mathematics"}
            ]
        ).clean()

    def test_subject_code_and_name_are_valid(self):
        make_snapshot(
            results_snapshot=[
                {
                    "subject_code": "MATH",
                    "subject_name": "Mathematics",
                }
            ]
        ).clean()

    def test_multiple_valid_results_are_valid(self):
        make_snapshot(
            results_snapshot=[
                {"subject_code": "MATH"},
                {"subject_name": "English"},
                {
                    "subject_code": "PHY",
                    "subject_name": "Physics",
                },
            ]
        ).clean()

    def test_term_without_school_id_is_allowed(self):
        make_snapshot(
            academic_term=make_term(
                school_id=None
            )
        ).clean()


# ---------------------------------------------------------------------------
# Sequence validation
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotSequenceValidation:
    @pytest.mark.parametrize(
        "value",
        [0, -1, -100],
    )
    def test_sequence_number_below_one_is_invalid(
        self,
        value,
    ):
        snapshot = make_snapshot(
            sequence_number=value
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "sequence_number",
            "Sequence number must be at least 1.",
        )

    @pytest.mark.parametrize(
        "value",
        [1, 2, 999],
    )
    def test_positive_sequence_is_valid(
        self,
        value,
    ):
        make_snapshot(
            sequence_number=value
        ).clean()

    def test_none_sequence_skips_model_clean_check(self):
        snapshot = make_snapshot(
            sequence_number=None
        )

        snapshot.clean()


# ---------------------------------------------------------------------------
# Numeric validation
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotNumericValidation:
    @pytest.mark.parametrize(
        ("field_name", "value", "message"),
        [
            (
                "term_gpa",
                Decimal("-0.001"),
                "Term GPA cannot be negative.",
            ),
            (
                "cumulative_gpa",
                Decimal("-0.001"),
                "Cumulative GPA cannot be negative.",
            ),
            (
                "credits_attempted",
                Decimal("-0.01"),
                "Credits attempted cannot be negative.",
            ),
            (
                "credits_earned",
                Decimal("-0.01"),
                "Credits earned cannot be negative.",
            ),
            (
                "term_aggregate",
                Decimal("-0.01"),
                "Term aggregate cannot be negative.",
            ),
        ],
    )
    def test_negative_numeric_values_are_invalid(
        self,
        field_name,
        value,
        message,
    ):
        kwargs = {field_name: value}

        if field_name == "credits_attempted":
            kwargs["credits_earned"] = Decimal("0.00")

        snapshot = make_snapshot(**kwargs)

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            field_name,
            message,
        )

    def test_credits_earned_cannot_exceed_attempted(self):
        snapshot = make_snapshot(
            credits_attempted=Decimal("10.00"),
            credits_earned=Decimal("10.01"),
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "credits_earned",
            "Credits earned cannot exceed credits attempted.",
        )

    def test_exceeds_attempted_error_overwrites_negative_error(self):
        snapshot = make_snapshot(
            credits_attempted=Decimal("-2.00"),
            credits_earned=Decimal("-1.00"),
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict[
            "credits_earned"
        ] == [
            "Credits earned cannot exceed credits attempted."
        ]
        assert exc_info.value.message_dict[
            "credits_attempted"
        ] == [
            "Credits attempted cannot be negative."
        ]

    def test_all_numeric_errors_are_collected(self):
        snapshot = make_snapshot(
            term_gpa=Decimal("-1.000"),
            cumulative_gpa=Decimal("-1.000"),
            credits_attempted=Decimal("-1.00"),
            credits_earned=Decimal("-2.00"),
            term_aggregate=Decimal("-1.00"),
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert set(exc_info.value.message_dict) == {
            "term_gpa",
            "cumulative_gpa",
            "credits_attempted",
            "credits_earned",
            "term_aggregate",
        }


# ---------------------------------------------------------------------------
# Label validation
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotLabelValidation:
    @pytest.mark.parametrize(
        "value",
        ["", " ", "   ", "\t", "\n"],
    )
    def test_academic_year_snapshot_required(
        self,
        value,
    ):
        snapshot = make_snapshot(
            academic_year_snapshot=value
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "academic_year_snapshot",
            "A frozen academic-year label is required.",
        )

    @pytest.mark.parametrize(
        "value",
        ["", " ", "   ", "\t", "\n"],
    )
    def test_term_name_snapshot_required(
        self,
        value,
    ):
        snapshot = make_snapshot(
            term_name_snapshot=value
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "term_name_snapshot",
            "A frozen academic-term label is required.",
        )

    def test_nonempty_labels_are_valid(self):
        make_snapshot(
            academic_year_snapshot="2025/2026",
            term_name_snapshot="Semester One",
        ).clean()


# ---------------------------------------------------------------------------
# results_snapshot validation
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotResultsValidation:
    @pytest.mark.parametrize(
        "value",
        [
            {},
            (),
            "results",
            1,
            True,
            None,
        ],
    )
    def test_results_snapshot_must_be_list(
        self,
        value,
    ):
        snapshot = make_snapshot(
            results_snapshot=value
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "results_snapshot",
            "Results snapshot must be stored as a JSON list.",
        )

    @pytest.mark.parametrize(
        "value",
        [
            "Mathematics",
            1,
            True,
            None,
            [],
            (),
        ],
    )
    def test_each_result_must_be_dict(
        self,
        value,
    ):
        snapshot = make_snapshot(
            results_snapshot=[value]
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "results_snapshot",
            "Item 1 must be a JSON object.",
        )

    @pytest.mark.parametrize(
        "value",
        [
            {},
            {"subject_code": ""},
            {"subject_name": ""},
            {
                "subject_code": None,
                "subject_name": None,
            },
            {
                "subject_code": False,
                "subject_name": False,
            },
            {"grade": "A"},
        ],
    )
    def test_result_requires_code_or_name(
        self,
        value,
    ):
        snapshot = make_snapshot(
            results_snapshot=[value]
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "results_snapshot",
            "Item 1 must contain subject_code or subject_name.",
        )

    def test_invalid_rows_are_all_reported(self):
        snapshot = make_snapshot(
            results_snapshot=[
                "invalid",
                {},
                {"subject_code": "MATH"},
                [],
                {"grade": "A"},
            ]
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict[
            "results_snapshot"
        ] == [
            "Item 1 must be a JSON object.",
            "Item 2 must contain subject_code or subject_name.",
            "Item 4 must be a JSON object.",
            "Item 5 must contain subject_code or subject_name.",
        ]

    def test_valid_rows_are_not_reported(self):
        snapshot = make_snapshot(
            results_snapshot=[
                {"subject_code": "MATH"},
                {},
                {"subject_name": "English"},
            ]
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert exc_info.value.message_dict[
            "results_snapshot"
        ] == [
            "Item 2 must contain subject_code or subject_name."
        ]


# ---------------------------------------------------------------------------
# School relationship validation
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotSchoolValidation:
    def test_term_must_match_transcript_school(self):
        snapshot = make_snapshot(
            transcript=make_transcript(
                school_id=1
            ),
            academic_term=make_term(
                school_id=2
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert_message(
            exc_info,
            "academic_term",
            "The academic term must belong to the same school as the "
            "transcript.",
        )

    def test_matching_school_is_valid(self):
        make_snapshot(
            transcript=make_transcript(
                school_id=1
            ),
            academic_term=make_term(
                school_id=1
            ),
        ).clean()

    def test_relationship_check_skipped_without_transcript_id(self):
        make_snapshot(
            transcript=make_transcript(
                pk=None,
                school_id=1,
            ),
            academic_term=make_term(
                school_id=2,
            ),
        ).clean()

    def test_relationship_check_skipped_without_term_id(self):
        make_snapshot(
            transcript=make_transcript(
                school_id=1,
            ),
            academic_term=make_term(
                pk=None,
                school_id=2,
            ),
        ).clean()


# ---------------------------------------------------------------------------
# Aggregated errors
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotAggregatedErrors:
    def test_errors_from_all_sections_are_collected(self):
        snapshot = make_snapshot(
            sequence_number=0,
            term_gpa=Decimal("-1.000"),
            cumulative_gpa=Decimal("-1.000"),
            credits_attempted=Decimal("-1.00"),
            credits_earned=Decimal("-2.00"),
            term_aggregate=Decimal("-1.00"),
            academic_year_snapshot=" ",
            term_name_snapshot=" ",
            results_snapshot={},
            transcript=make_transcript(
                school_id=1
            ),
            academic_term=make_term(
                school_id=2
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.clean()

        assert set(exc_info.value.message_dict) == {
            "sequence_number",
            "term_gpa",
            "cumulative_gpa",
            "credits_attempted",
            "credits_earned",
            "term_aggregate",
            "academic_year_snapshot",
            "term_name_snapshot",
            "results_snapshot",
            "academic_term",
        }


# ---------------------------------------------------------------------------
# save() immutability
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotSave:
    def test_existing_snapshot_cannot_be_saved(self):
        snapshot = make_snapshot(
            pk=999
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.save()

        assert exc_info.value.messages == [
            "Transcript GPA snapshots are immutable and cannot be modified."
        ]

    def test_new_snapshot_calls_full_clean(
        self,
        monkeypatch,
    ):
        snapshot = make_snapshot(
            pk=None
        )
        called = {"value": False}

        def fake_full_clean(*args, **kwargs):
            called["value"] = True

        def fake_save(self, *args, **kwargs):
            return "saved"

        monkeypatch.setattr(
            snapshot,
            "full_clean",
            fake_full_clean,
        )
        monkeypatch.setattr(
            models.Model,
            "save",
            fake_save,
        )

        result = snapshot.save()

        assert called["value"] is True
        assert result == "saved"

    def test_validation_error_from_full_clean_propagates(
        self,
        monkeypatch,
    ):
        snapshot = make_snapshot(
            pk=None
        )

        def fake_full_clean(*args, **kwargs):
            raise ValidationError(
                {"term_gpa": ["Invalid GPA."]}
            )

        monkeypatch.setattr(
            snapshot,
            "full_clean",
            fake_full_clean,
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.save()

        assert exc_info.value.message_dict == {
            "term_gpa": ["Invalid GPA."]
        }

    def test_existing_snapshot_does_not_call_full_clean(
        self,
        monkeypatch,
    ):
        snapshot = make_snapshot(
            pk=999
        )
        called = {"value": False}

        def fake_full_clean(*args, **kwargs):
            called["value"] = True

        monkeypatch.setattr(
            snapshot,
            "full_clean",
            fake_full_clean,
        )

        with pytest.raises(ValidationError):
            snapshot.save()

        assert called["value"] is False


# ---------------------------------------------------------------------------
# delete protection
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotDelete:
    def test_delete_always_raises(self):
        snapshot = make_snapshot()

        with pytest.raises(ValidationError) as exc_info:
            snapshot.delete()

        assert exc_info.value.messages == [
            "Transcript GPA snapshots cannot be deleted independently."
        ]

    def test_delete_existing_snapshot_also_raises(self):
        snapshot = make_snapshot(
            pk=1000
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.delete()

        assert exc_info.value.messages == [
            "Transcript GPA snapshots cannot be deleted independently."
        ]


# ---------------------------------------------------------------------------
# String representation
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotStringRepresentation:
    def test_string_representation(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            TranscriptRecord,
            "__str__",
            lambda self: "Official transcript — Alice — v1",
        )

        snapshot = make_snapshot(
            academic_year_snapshot="2025/2026",
            term_name_snapshot="Term One",
        )

        assert str(snapshot) == (
            "Official transcript — Alice — v1 — "
            "2025/2026 Term One"
        )

    def test_string_contains_transcript(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            TranscriptRecord,
            "__str__",
            lambda self: "Transcript X",
        )

        assert "Transcript X" in str(
            make_snapshot()
        )

    def test_string_contains_year_and_term(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            TranscriptRecord,
            "__str__",
            lambda self: "Transcript",
        )

        text = str(
            make_snapshot(
                academic_year_snapshot="2024/2025",
                term_name_snapshot="Semester Two",
            )
        )

        assert "2024/2025" in text
        assert "Semester Two" in text


# ---------------------------------------------------------------------------
# full_clean field validation without database access
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotFullClean:
    @staticmethod
    def exclusions():
        return [
            "transcript",
            "academic_term",
        ]

    def test_missing_sequence_number_is_rejected(self):
        snapshot = make_snapshot(
            sequence_number=None
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert "sequence_number" in exc_info.value.message_dict

    def test_missing_academic_year_snapshot_is_rejected(self):
        snapshot = make_snapshot(
            academic_year_snapshot=""
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "academic_year_snapshot"
            in exc_info.value.message_dict
        )

    def test_missing_term_name_snapshot_is_rejected(self):
        snapshot = make_snapshot(
            term_name_snapshot=""
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "term_name_snapshot"
            in exc_info.value.message_dict
        )

    def test_academic_year_snapshot_max_length_enforced(self):
        snapshot = make_snapshot(
            academic_year_snapshot="X" * 101
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "academic_year_snapshot"
            in exc_info.value.message_dict
        )

    def test_term_name_snapshot_max_length_enforced(self):
        snapshot = make_snapshot(
            term_name_snapshot="X" * 101
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "term_name_snapshot"
            in exc_info.value.message_dict
        )

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("term_gpa", Decimal("1234.567")),
            ("cumulative_gpa", Decimal("1234.567")),
            (
                "credits_attempted",
                Decimal("123456789.12"),
            ),
            (
                "credits_earned",
                Decimal("123456789.12"),
            ),
            (
                "term_aggregate",
                Decimal("123456789.12"),
            ),
        ],
    )
    def test_decimal_max_digits_enforced(
        self,
        field_name,
        value,
    ):
        snapshot = make_snapshot(
            **{field_name: value}
        )

        with pytest.raises(ValidationError) as exc_info:
            snapshot.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert field_name in exc_info.value.message_dict


# ---------------------------------------------------------------------------
# Parent clean behavior
# ---------------------------------------------------------------------------

class TestTranscriptGPASnapshotSuperClean:
    def test_clean_calls_model_parent(
        self,
        monkeypatch,
    ):
        called = {"value": False}

        def fake_clean(self):
            called["value"] = True

        monkeypatch.setattr(
            models.Model,
            "clean",
            fake_clean,
        )

        make_snapshot().clean()

        assert called["value"] is True

    def test_parent_validation_error_propagates(
        self,
        monkeypatch,
    ):
        def fake_clean(self):
            raise ValidationError(
                {"base": ["Parent validation failed."]}
            )

        monkeypatch.setattr(
            models.Model,
            "clean",
            fake_clean,
        )

        with pytest.raises(ValidationError) as exc_info:
            make_snapshot().clean()

        assert exc_info.value.message_dict == {
            "base": ["Parent validation failed."]
        }