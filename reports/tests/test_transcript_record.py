"""
Enterprise-grade tests for TranscriptRecord.

Save as:
    reports/tests/test_transcript_record.py

Run:
    pytest reports/tests/test_transcript_record.py -q
"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from accounts.models import StudentProfile, User
from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedModel,
    VersionedModel,
)


from reports.models.transcripts import TranscriptRecord



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def field(name):
    return TranscriptRecord._meta.get_field(name)


def constraint(name):
    return next(
        item
        for item in TranscriptRecord._meta.constraints
        if item.name == name
    )


def index(name):
    return next(
        item
        for item in TranscriptRecord._meta.indexes
        if item.name == name
    )


def make_user(
    *,
    pk=10,
    school_id=1,
    is_superuser=False,
    is_active=True,
):
    return User(
        pk=pk,
        email=f"user{pk}@example.com",
        school_id=school_id,
        is_superuser=is_superuser,
        is_active=is_active,
    )


def make_student(
    *,
    pk=20,
    school_id=1,
):
    return StudentProfile(
        pk=pk,
        user=make_user(
            pk=pk,
            school_id=school_id,
        ),
        school_id=school_id,
    )


def make_transcript(**overrides):
    values = {
        "pk": None,
        "school_id": 1,
        "student": make_student(),
        "is_official": False,
        "verification_code": "TRANSCRIPT-VERIFY-001",
        "cumulative_gpa": Decimal("3.750"),
        "credits_earned_total": Decimal("120.00"),
        "student_name_snapshot": "Alice Student",
        "identification_number_snapshot": "STU-001",
        "programme_snapshot": "Bachelor of Science",
        "grading_policy_snapshot": {
            "scale": "4.0",
            "pass_mark": "2.0",
        },
        "issued_by": None,
        "issued_at": None,
        "version": 1,
        "root_id": "transcript-chain-001",
        "is_latest": True,
        "previous_version": None,
    }
    values.update(overrides)
    return TranscriptRecord(**values)


def assert_message(exc_info, key, expected):
    assert exc_info.value.message_dict[key] == [expected]


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------

class TestTranscriptRecordInheritance:
    def test_is_django_model(self):
        assert issubclass(TranscriptRecord, models.Model)

    def test_inherits_abstract_generated_artifact(self):
        assert issubclass(
            TranscriptRecord,
            AbstractGeneratedArtifact,
        )

    def test_inherits_versioned_model(self):
        assert issubclass(
            TranscriptRecord,
            VersionedModel,
        )

    def test_inherits_school_scoped_model(self):
        assert issubclass(
            TranscriptRecord,
            SchoolScopedModel,
        )

    def test_model_is_concrete(self):
        assert TranscriptRecord._meta.abstract is False


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class TestTranscriptRecordMeta:
    def test_ordering(self):
        assert TranscriptRecord._meta.ordering == [
            "-issued_at",
            "-created_at",
        ]

    def test_constraint_count(self):
        assert len(TranscriptRecord._meta.constraints) == 6

    @pytest.mark.parametrize(
        "name",
        [
            "transcript_cumulative_gpa_nonnegative",
            "transcript_credits_total_nonnegative",
            "transcript_version_gte_1",
            "official_transcript_requires_issue_date",
            "unique_transcript_chain_version",
            "unique_latest_transcript_version",
        ],
    )
    def test_constraint_exists(self, name):
        assert constraint(name).name == name

    def test_chain_version_unique_fields(self):
        item = constraint("unique_transcript_chain_version")

        assert tuple(item.fields) == (
            "school",
            "root_id",
            "version",
        )

    def test_latest_unique_fields(self):
        item = constraint("unique_latest_transcript_version")

        assert tuple(item.fields) == (
            "school",
            "root_id",
        )

    def test_latest_unique_condition(self):
        item = constraint("unique_latest_transcript_version")

        assert item.condition == Q(is_latest=True)

    def test_index_count(self):
        assert len(TranscriptRecord._meta.indexes) == 4

    @pytest.mark.parametrize(
        ("name", "expected_fields"),
        [
            (
                "tr_school_stu_type_idx",
                ["school", "student", "is_official"],
            ),
            (
                "transcript_school_issue_idx",
                ["school", "is_official", "-issued_at"],
            ),
            (
                "transcript_student_history_idx",
                ["student", "-issued_at"],
            ),
            (
                "transcript_root_version_idx",
                ["root_id", "version"],
            ),
        ],
    )
    def test_index_fields(self, name, expected_fields):
        assert list(index(name).fields) == expected_fields


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------

class TestTranscriptRecordFields:
    def test_student_foreign_key(self):
        item = field("student")

        assert isinstance(item, models.ForeignKey)
        assert item.remote_field.model is StudentProfile
        assert item.remote_field.on_delete is models.PROTECT
        assert item.remote_field.related_name == "transcripts"
        assert item.null is False
        assert item.blank is False

    def test_is_official_metadata(self):
        item = field("is_official")

        assert isinstance(item, models.BooleanField)
        assert item.default is False
        assert item.db_index is True

    def test_verification_code_metadata(self):
        item = field("verification_code")

        assert isinstance(item, models.CharField)
        assert item.max_length == 64
        assert item.unique is True
        assert item.db_index is True
        assert item.null is False
        assert item.blank is False

    @pytest.mark.parametrize(
        ("field_name", "max_digits", "decimal_places"),
        [
            ("cumulative_gpa", 6, 3),
            ("credits_earned_total", 10, 2),
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
        assert item.null is True
        assert item.blank is True

    def test_student_name_snapshot_metadata(self):
        item = field("student_name_snapshot")

        assert isinstance(item, models.CharField)
        assert item.max_length == 200
        assert item.blank is False
        assert item.null is False

    @pytest.mark.parametrize(
        ("field_name", "max_length"),
        [
            ("identification_number_snapshot", 100),
            ("programme_snapshot", 200),
        ],
    )
    def test_optional_snapshot_text_metadata(
        self,
        field_name,
        max_length,
    ):
        item = field(field_name)

        assert isinstance(item, models.CharField)
        assert item.max_length == max_length
        assert item.blank is True
        assert item.default == ""

    def test_grading_policy_snapshot_metadata(self):
        item = field("grading_policy_snapshot")

        assert isinstance(item, models.JSONField)
        assert item.default is dict
        assert item.blank is True

    def test_issued_by_metadata(self):
        item = field("issued_by")

        assert isinstance(item, models.ForeignKey)
        assert item.remote_field.on_delete is models.SET_NULL
        assert item.remote_field.related_name == "issued_transcripts"
        assert item.null is True
        assert item.blank is True

    def test_issued_at_metadata(self):
        item = field("issued_at")

        assert isinstance(item, models.DateTimeField)
        assert item.null is True
        assert item.blank is True
        assert item.db_index is True


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestTranscriptRecordDefaults:
    def test_is_official_defaults_false(self):
        assert TranscriptRecord().is_official is False

    def test_identification_snapshot_defaults_empty(self):
        assert (
            TranscriptRecord().identification_number_snapshot
            == ""
        )

    def test_programme_snapshot_defaults_empty(self):
        assert TranscriptRecord().programme_snapshot == ""

    def test_grading_policy_defaults_empty_dict(self):
        assert TranscriptRecord().grading_policy_snapshot == {}

    def test_grading_policy_default_not_shared(self):
        first = TranscriptRecord()
        second = TranscriptRecord()

        assert (
            first.grading_policy_snapshot
            is not second.grading_policy_snapshot
        )

    @pytest.mark.parametrize(
        "field_name",
        [
            "cumulative_gpa",
            "credits_earned_total",
            "issued_by",
            "issued_at",
        ],
    )
    def test_nullable_fields_default_none(self, field_name):
        assert getattr(TranscriptRecord(), field_name) is None


# ---------------------------------------------------------------------------
# Valid states
# ---------------------------------------------------------------------------

class TestTranscriptRecordValidStates:
    def test_unofficial_transcript_without_issue_date_is_valid(self):
        make_transcript(
            is_official=False,
            issued_at=None,
        ).clean()

    def test_official_transcript_with_issue_date_is_valid(self):
        make_transcript(
            is_official=True,
            issued_at=datetime(
                2026,
                7,
                21,
                tzinfo=timezone.utc,
            ),
        ).clean()

    def test_optional_numeric_values_can_be_none(self):
        make_transcript(
            cumulative_gpa=None,
            credits_earned_total=None,
        ).clean()

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("cumulative_gpa", Decimal("0.000")),
            (
                "credits_earned_total",
                Decimal("0.00"),
            ),
        ],
    )
    def test_zero_numeric_boundary_is_valid(
        self,
        field_name,
        value,
    ):
        make_transcript(
            **{field_name: value}
        ).clean()

    def test_empty_grading_policy_dict_is_valid(self):
        make_transcript(
            grading_policy_snapshot={}
        ).clean()

    def test_superuser_from_another_school_may_issue(self):
        issuer = make_user(
            school_id=999,
            is_superuser=True,
            is_active=True,
        )

        make_transcript(
            issued_by=issuer,
        ).clean()

    def test_related_student_without_school_is_allowed(self):
        student = make_student(
            school_id=None,
        )

        make_transcript(
            student=student,
        ).clean()

    def test_issuer_without_school_is_allowed(self):
        issuer = make_user(
            school_id=None,
            is_active=True,
        )

        make_transcript(
            issued_by=issuer,
        ).clean()

    def test_school_checks_skipped_without_transcript_school(self):
        make_transcript(
            school_id=None,
            student=make_student(
                school_id=2,
            ),
            issued_by=make_user(
                school_id=3,
                is_active=True,
            ),
        ).clean()


# ---------------------------------------------------------------------------
# Student validation
# ---------------------------------------------------------------------------

class TestTranscriptRecordStudentValidation:
    def test_student_must_match_school(self):
        transcript = make_transcript(
            school_id=1,
            student=make_student(
                school_id=2,
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "student",
            "The student must belong to the same school as the "
            "transcript.",
        )

    def test_student_check_skipped_without_student_id(self):
        student = make_student(
            pk=None,
            school_id=2,
        )

        make_transcript(
            student=student,
            school_id=1,
        ).clean()


# ---------------------------------------------------------------------------
# Issuer validation
# ---------------------------------------------------------------------------

class TestTranscriptRecordIssuerValidation:
    def test_non_superuser_issuer_must_match_school(self):
        transcript = make_transcript(
            school_id=1,
            issued_by=make_user(
                school_id=2,
                is_superuser=False,
                is_active=True,
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "issued_by",
            "The issuing user must belong to the same school as the "
            "transcript.",
        )

    def test_inactive_issuer_is_invalid(self):
        transcript = make_transcript(
            issued_by=make_user(
                school_id=1,
                is_active=False,
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "issued_by",
            "An inactive user cannot issue a transcript.",
        )

    def test_inactive_superuser_is_still_invalid(self):
        transcript = make_transcript(
            issued_by=make_user(
                school_id=999,
                is_superuser=True,
                is_active=False,
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "issued_by",
            "An inactive user cannot issue a transcript.",
        )

    def test_inactive_error_overwrites_school_error(self):
        transcript = make_transcript(
            school_id=1,
            issued_by=make_user(
                school_id=2,
                is_superuser=False,
                is_active=False,
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "issued_by",
            "An inactive user cannot issue a transcript.",
        )

    def test_issuer_check_skipped_without_issuer_id(self):
        issuer = make_user(
            pk=None,
            school_id=2,
            is_active=False,
        )

        make_transcript(
            school_id=1,
            issued_by=issuer,
        ).clean()


# ---------------------------------------------------------------------------
# Official issue-date validation
# ---------------------------------------------------------------------------

class TestTranscriptRecordOfficialValidation:
    def test_official_transcript_requires_issue_date(self):
        transcript = make_transcript(
            is_official=True,
            issued_at=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "issued_at",
            "An official transcript must have an issue date.",
        )

    def test_unofficial_transcript_does_not_require_issue_date(self):
        make_transcript(
            is_official=False,
            issued_at=None,
        ).clean()


# ---------------------------------------------------------------------------
# Numeric validation
# ---------------------------------------------------------------------------

class TestTranscriptRecordNumericValidation:
    def test_negative_cumulative_gpa_is_invalid(self):
        transcript = make_transcript(
            cumulative_gpa=Decimal("-0.001")
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "cumulative_gpa",
            "Cumulative GPA cannot be negative.",
        )

    def test_negative_credits_total_is_invalid(self):
        transcript = make_transcript(
            credits_earned_total=Decimal("-0.01")
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "credits_earned_total",
            "Total credits earned cannot be negative.",
        )

    def test_numeric_errors_are_collected(self):
        transcript = make_transcript(
            cumulative_gpa=Decimal("-1.000"),
            credits_earned_total=Decimal("-1.00"),
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert set(exc_info.value.message_dict) == {
            "cumulative_gpa",
            "credits_earned_total",
        }


# ---------------------------------------------------------------------------
# Snapshot validation
# ---------------------------------------------------------------------------

class TestTranscriptRecordSnapshotValidation:
    @pytest.mark.parametrize(
        "value",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
        ],
    )
    def test_student_name_snapshot_must_not_be_blank(
        self,
        value,
    ):
        transcript = make_transcript(
            student_name_snapshot=value
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "student_name_snapshot",
            "A frozen student name is required.",
        )

    @pytest.mark.parametrize(
        "value",
        [
            [],
            (),
            "policy",
            1,
            True,
            None,
        ],
    )
    def test_grading_policy_snapshot_must_be_dict(
        self,
        value,
    ):
        transcript = make_transcript(
            grading_policy_snapshot=value
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "grading_policy_snapshot",
            "Grading policy snapshot must be stored as a JSON object.",
        )

    def test_nonempty_student_name_is_valid(self):
        make_transcript(
            student_name_snapshot="Alice"
        ).clean()

    def test_complex_grading_policy_dict_is_valid(self):
        make_transcript(
            grading_policy_snapshot={
                "name": "University GPA",
                "scale": [
                    {"grade": "A", "points": 4.0},
                    {"grade": "B", "points": 3.0},
                ],
            }
        ).clean()


# ---------------------------------------------------------------------------
# Previous-version validation
# ---------------------------------------------------------------------------

class TestTranscriptRecordPreviousVersionValidation:
    def previous(self, **overrides):
        values = {
            "pk": 100,
            "school_id": 1,
            "student": make_student(
                pk=20,
                school_id=1,
            ),
            "student_name_snapshot": "Alice Student",
            "verification_code": "PREVIOUS-001",
            "version": 1,
            "root_id": "transcript-chain-001",
            "is_latest": False,
        }
        values.update(overrides)
        return TranscriptRecord(**values)

    def test_cannot_reference_itself(self):
        previous = self.previous(pk=100)
        transcript = make_transcript(
            pk=100,
            previous_version=previous,
            version=2,
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "previous_version",
            "A transcript cannot reference itself as its previous version.",
        )

    def test_previous_version_must_match_school(self):
        previous = self.previous(
            school_id=2,
        )
        transcript = make_transcript(
            school_id=1,
            previous_version=previous,
            version=2,
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "previous_version",
            "The previous transcript version must belong to the same "
            "school.",
        )

    def test_previous_version_must_match_student(self):
        previous = self.previous(
            student=make_student(
                pk=999,
                school_id=1,
            )
        )
        transcript = make_transcript(
            student=make_student(
                pk=20,
                school_id=1,
            ),
            previous_version=previous,
            version=2,
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "previous_version",
            "The previous transcript version must belong to the same "
            "student.",
        )

    def test_previous_version_must_match_root(self):
        previous = self.previous(
            root_id="different-root"
        )
        transcript = make_transcript(
            previous_version=previous,
            root_id="transcript-chain-001",
            version=2,
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "previous_version",
            "The previous transcript version must belong to the same "
            "version chain.",
        )

    @pytest.mark.parametrize(
        ("previous_version_number", "current_version"),
        [
            (2, 2),
            (3, 2),
            (10, 2),
        ],
    )
    def test_previous_version_number_must_be_lower(
        self,
        previous_version_number,
        current_version,
    ):
        previous = self.previous(
            version=previous_version_number
        )
        transcript = make_transcript(
            previous_version=previous,
            version=current_version,
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert_message(
            exc_info,
            "previous_version",
            "The previous transcript must have a lower version number.",
        )

    def test_valid_previous_version_chain(self):
        previous = self.previous(
            version=1
        )
        transcript = make_transcript(
            previous_version=previous,
            version=2,
        )

        transcript.clean()

    def test_previous_version_checks_use_elif_priority(self):
        previous = self.previous(
            school_id=2,
            student=make_student(
                pk=999,
                school_id=2,
            ),
            root_id="wrong-root",
            version=99,
        )
        transcript = make_transcript(
            school_id=1,
            previous_version=previous,
            version=2,
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert exc_info.value.message_dict["previous_version"] == [
            "The previous transcript version must belong to the same "
            "school."
        ]


# ---------------------------------------------------------------------------
# Aggregated validation errors
# ---------------------------------------------------------------------------

class TestTranscriptRecordAggregatedErrors:
    def test_multiple_independent_errors_are_collected(self):
        transcript = make_transcript(
            student=make_student(
                school_id=2,
            ),
            is_official=True,
            issued_at=None,
            cumulative_gpa=Decimal("-1.000"),
            credits_earned_total=Decimal("-1.00"),
            student_name_snapshot=" ",
            grading_policy_snapshot=[],
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.clean()

        assert set(exc_info.value.message_dict) == {
            "student",
            "issued_at",
            "cumulative_gpa",
            "credits_earned_total",
            "student_name_snapshot",
            "grading_policy_snapshot",
        }


# ---------------------------------------------------------------------------
# String representation
# ---------------------------------------------------------------------------

class TestTranscriptRecordStringRepresentation:
    def test_unofficial_string(self):
        transcript = make_transcript(
            is_official=False,
            student_name_snapshot="Alice Student",
            version=3,
        )

        assert str(transcript) == (
            "Unofficial transcript — Alice Student — v3"
        )

    def test_official_string(self):
        transcript = make_transcript(
            is_official=True,
            student_name_snapshot="Alice Student",
            version=4,
        )

        assert str(transcript) == (
            "Official transcript — Alice Student — v4"
        )

    @pytest.mark.parametrize(
        ("is_official", "expected"),
        [
            (False, "Unofficial"),
            (True, "Official"),
        ],
    )
    def test_string_kind(
        self,
        is_official,
        expected,
    ):
        assert str(
            make_transcript(
                is_official=is_official
            )
        ).startswith(expected)

    def test_string_contains_snapshot_name(self):
        text = str(
            make_transcript(
                student_name_snapshot="Bob Example"
            )
        )

        assert "Bob Example" in text

    def test_string_contains_version(self):
        assert str(
            make_transcript(
                version=12
            )
        ).endswith("v12")


# ---------------------------------------------------------------------------
# full_clean field-level validation without database queries
# ---------------------------------------------------------------------------

class TestTranscriptRecordFullClean:
    @staticmethod
    def exclusions():
        return [
            "school",
            "student",
            "issued_by",
            "created_by",
            "updated_by",
            "previous_version",
        ]

    def test_missing_verification_code_is_rejected(self):
        transcript = make_transcript(
            verification_code=""
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert "verification_code" in exc_info.value.message_dict

    def test_verification_code_over_max_length_is_rejected(self):
        transcript = make_transcript(
            verification_code="X" * 65
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert "verification_code" in exc_info.value.message_dict

    def test_student_name_over_max_length_is_rejected(self):
        transcript = make_transcript(
            student_name_snapshot="X" * 201
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "student_name_snapshot"
            in exc_info.value.message_dict
        )

    def test_identification_number_over_max_length_is_rejected(self):
        transcript = make_transcript(
            identification_number_snapshot="X" * 101
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "identification_number_snapshot"
            in exc_info.value.message_dict
        )

    def test_programme_over_max_length_is_rejected(self):
        transcript = make_transcript(
            programme_snapshot="X" * 201
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert "programme_snapshot" in exc_info.value.message_dict

    def test_cumulative_gpa_max_digits_enforced(self):
        transcript = make_transcript(
            cumulative_gpa=Decimal("1234.567")
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert "cumulative_gpa" in exc_info.value.message_dict

    def test_credits_total_max_digits_enforced(self):
        transcript = make_transcript(
            credits_earned_total=Decimal("123456789.12")
        )

        with pytest.raises(ValidationError) as exc_info:
            transcript.full_clean(
                exclude=self.exclusions(),
                validate_unique=False,
                validate_constraints=False,
            )

        assert (
            "credits_earned_total"
            in exc_info.value.message_dict
        )


# ---------------------------------------------------------------------------
# clean() superclass behavior
# ---------------------------------------------------------------------------

class TestTranscriptRecordSuperClean:
    def test_clean_calls_parent_clean(self, monkeypatch):
        called = {"value": False}

        def fake_parent_clean(self):
            called["value"] = True

        monkeypatch.setattr(
            AbstractGeneratedArtifact,
            "clean",
            fake_parent_clean,
        )

        make_transcript().clean()

        assert called["value"] is True

    def test_parent_validation_error_propagates(self, monkeypatch):
        def fake_parent_clean(self):
            raise ValidationError(
                {"status": ["Parent validation failed."]}
            )

        monkeypatch.setattr(
            AbstractGeneratedArtifact,
            "clean",
            fake_parent_clean,
        )

        with pytest.raises(ValidationError) as exc_info:
            make_transcript().clean()

        assert exc_info.value.message_dict == {
            "status": ["Parent validation failed."]
        }