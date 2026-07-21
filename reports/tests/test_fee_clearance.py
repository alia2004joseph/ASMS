"""
Comprehensive model tests for FeeClearanceCertificate.

Expected location:
    reports/tests/test_fee_clearance.py

Run with:
    pytest reports/tests/test_fee_clearance.py -q
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import StudentProfile, User
from academics.models import AcademicTerm, AcademicYear
from reports.constants import ClearanceStatus
from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedModel,
    VersionedModel,
)

try:
    from reports.models.fee_clearance import FeeClearanceCertificate
except ImportError:
    from reports.models import FeeClearanceCertificate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def model_field(model, name):
    return model._meta.get_field(name)


def constraint_by_name(name):
    return next(
        constraint
        for constraint in FeeClearanceCertificate._meta.constraints
        if constraint.name == name
    )


def index_by_name(name):
    return next(
        index
        for index in FeeClearanceCertificate._meta.indexes
        if index.name == name
    )


def make_user(
    *,
    pk=10,
    school_id=1,
    first_name="Admin",
    role=User.Role.ADMIN,
    is_active=True,
):
    return User(
        pk=pk,
        email=f"user{pk}@example.com",
        first_name=first_name,
        role=role,
        school_id=school_id,
        is_active=is_active,
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


def make_academic_year(*, pk=30, school_id=1):
    return AcademicYear(pk=pk, school_id=school_id)


def make_term(*, pk=40, school_id=1):
    return AcademicTerm(pk=pk, school_id=school_id)


def make_certificate(**overrides):
    values = {
        "pk": 1,
        "school_id": 1,
        "student": make_student(),
        "academic_year": make_academic_year(),
        "term": make_term(),
        "cleared_amount": Decimal("1000.00"),
        "outstanding_balance": Decimal("0.00"),
        "clearance_status": ClearanceStatus.CLEARED,
        "certificate_number": "FCC-2026-0001",
        "verification_code": "VERIFY-0001",
        "override_reason": "",
        "override_by": None,
        "issued_by": make_user(pk=11),
        "issued_at": timezone.now(),
        "root_id": UUID("11111111-1111-1111-1111-111111111111"),
        "version": 1,
        "is_latest": True,
        "is_revoked": False,
        "revoked_reason": "",
        "revoked_at": None,
        "revoked_by": None,
    }
    values.update(overrides)
    return FeeClearanceCertificate(**values)


# ---------------------------------------------------------------------------
# Inheritance and manager behavior
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateInheritance:
    def test_is_django_model(self):
        assert issubclass(FeeClearanceCertificate, models.Model)

    def test_inherits_generated_artifact(self):
        assert issubclass(
            FeeClearanceCertificate,
            AbstractGeneratedArtifact,
        )

    def test_inherits_versioned_model(self):
        assert issubclass(FeeClearanceCertificate, VersionedModel)

    def test_inherits_school_scoped_model(self):
        assert issubclass(
            FeeClearanceCertificate,
            SchoolScopedModel,
        )

    def test_model_is_not_abstract(self):
        assert FeeClearanceCertificate._meta.abstract is False

    def test_uses_school_scoped_manager(self):
        assert hasattr(FeeClearanceCertificate.objects, "for_school")


# ---------------------------------------------------------------------------
# Meta configuration
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateMeta:
    def test_ordering(self):
        assert FeeClearanceCertificate._meta.ordering == ["-issued_at"]

    @pytest.mark.parametrize(
        "name",
        [
            "fee_clearance_cleared_amount_positive",
            "fee_clearance_balance_positive",
            "fee_clearance_override_reason_required",
            "unique_fee_clearance_version",
            "unique_latest_fee_clearance",
        ],
    )
    def test_constraint_exists(self, name):
        assert constraint_by_name(name).name == name

    def test_constraint_count(self):
        assert len(FeeClearanceCertificate._meta.constraints) == 5

    @pytest.mark.parametrize(
        ("name", "expected_fields"),
        [
            (
                "fee_clearance_student_term_idx",
                ["school", "student", "term"],
            ),
            (
                "fee_clearance_status_idx",
                ["school", "clearance_status"],
            ),
            (
                "fee_clearance_issued_idx",
                ["school", "issued_at"],
            ),
            (
                "fee_clearance_version_idx",
                ["root_id", "version"],
            ),
        ],
    )
    def test_index_fields(self, name, expected_fields):
        assert list(index_by_name(name).fields) == expected_fields

    def test_index_count(self):
        assert len(FeeClearanceCertificate._meta.indexes) == 4

    def test_version_constraint_fields(self):
        constraint = constraint_by_name(
            "unique_fee_clearance_version"
        )
        assert tuple(constraint.fields) == (
            "school",
            "root_id",
            "version",
        )

    def test_latest_constraint_fields(self):
        constraint = constraint_by_name(
            "unique_latest_fee_clearance"
        )
        assert tuple(constraint.fields) == ("school", "root_id")

    def test_latest_constraint_is_conditional(self):
        constraint = constraint_by_name(
            "unique_latest_fee_clearance"
        )
        assert constraint.condition == models.Q(is_latest=True)


# ---------------------------------------------------------------------------
# Foreign keys
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateForeignKeys:
    @pytest.mark.parametrize(
        ("field_name", "related_model_name", "on_delete"),
        [
            ("student", "StudentProfile", models.PROTECT),
            ("academic_year", "AcademicYear", models.PROTECT),
            ("term", "AcademicTerm", models.PROTECT),
            ("override_by", "User", models.SET_NULL),
            ("issued_by", "User", models.SET_NULL),
        ],
    )
    def test_foreign_key_configuration(
        self,
        field_name,
        related_model_name,
        on_delete,
    ):
        field = model_field(FeeClearanceCertificate, field_name)

        assert isinstance(field, models.ForeignKey)
        assert field.remote_field.model.__name__ == related_model_name
        assert field.remote_field.on_delete is on_delete

    def test_student_related_name(self):
        field = model_field(FeeClearanceCertificate, "student")
        assert (
            field.remote_field.related_name
            == "fee_clearance_certificates"
        )

    @pytest.mark.parametrize(
        "field_name",
        ["academic_year", "term"],
    )
    def test_academic_related_name_is_disabled(self, field_name):
        field = model_field(FeeClearanceCertificate, field_name)
        assert field.remote_field.related_name == "+"

    def test_override_by_related_name(self):
        field = model_field(FeeClearanceCertificate, "override_by")
        assert (
            field.remote_field.related_name
            == "fee_clearance_overrides"
        )

    def test_issued_by_related_name(self):
        field = model_field(FeeClearanceCertificate, "issued_by")
        assert (
            field.remote_field.related_name
            == "issued_fee_clearance_certificates"
        )

    @pytest.mark.parametrize(
        "field_name",
        ["override_by", "issued_by"],
    )
    def test_optional_user_fields_allow_null_and_blank(
        self,
        field_name,
    ):
        field = model_field(FeeClearanceCertificate, field_name)

        assert field.null is True
        assert field.blank is True

    @pytest.mark.parametrize(
        "field_name",
        ["student", "academic_year", "term"],
    )
    def test_required_foreign_keys_do_not_allow_null(
        self,
        field_name,
    ):
        assert model_field(
            FeeClearanceCertificate,
            field_name,
        ).null is False


# ---------------------------------------------------------------------------
# Monetary fields
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateMoneyFields:
    @pytest.mark.parametrize(
        "field_name",
        ["cleared_amount", "outstanding_balance"],
    )
    def test_is_decimal_field(self, field_name):
        assert isinstance(
            model_field(FeeClearanceCertificate, field_name),
            models.DecimalField,
        )

    @pytest.mark.parametrize(
        "field_name",
        ["cleared_amount", "outstanding_balance"],
    )
    def test_max_digits(self, field_name):
        assert model_field(
            FeeClearanceCertificate,
            field_name,
        ).max_digits == 14

    @pytest.mark.parametrize(
        "field_name",
        ["cleared_amount", "outstanding_balance"],
    )
    def test_decimal_places(self, field_name):
        assert model_field(
            FeeClearanceCertificate,
            field_name,
        ).decimal_places == 2

    @pytest.mark.parametrize(
        "field_name",
        ["cleared_amount", "outstanding_balance"],
    )
    def test_default_is_zero_decimal(self, field_name):
        field = model_field(FeeClearanceCertificate, field_name)
        assert field.get_default() == Decimal("0.00")

    def test_instance_defaults_are_decimals(self):
        certificate = FeeClearanceCertificate()

        assert certificate.cleared_amount == Decimal("0.00")
        assert certificate.outstanding_balance == Decimal("0.00")


# ---------------------------------------------------------------------------
# Text and status fields
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateFieldMetadata:
    def test_clearance_status_is_char_field(self):
        assert isinstance(
            model_field(
                FeeClearanceCertificate,
                "clearance_status",
            ),
            models.CharField,
        )

    def test_clearance_status_max_length(self):
        assert model_field(
            FeeClearanceCertificate,
            "clearance_status",
        ).max_length == 30

    def test_clearance_status_choices(self):
        assert tuple(
            model_field(
                FeeClearanceCertificate,
                "clearance_status",
            ).choices
        ) == tuple(ClearanceStatus.choices)

    def test_clearance_status_is_indexed(self):
        assert model_field(
            FeeClearanceCertificate,
            "clearance_status",
        ).db_index is True

    @pytest.mark.parametrize(
        "field_name",
        ["certificate_number", "verification_code"],
    )
    def test_public_identifiers_are_unique(self, field_name):
        assert model_field(
            FeeClearanceCertificate,
            field_name,
        ).unique is True

    @pytest.mark.parametrize(
        "field_name",
        ["certificate_number", "verification_code"],
    )
    def test_public_identifiers_are_indexed(self, field_name):
        assert model_field(
            FeeClearanceCertificate,
            field_name,
        ).db_index is True

    @pytest.mark.parametrize(
        "field_name",
        ["certificate_number", "verification_code"],
    )
    def test_public_identifiers_max_length(self, field_name):
        assert model_field(
            FeeClearanceCertificate,
            field_name,
        ).max_length == 64

    def test_verification_code_help_text(self):
        assert (
            model_field(
                FeeClearanceCertificate,
                "verification_code",
            ).help_text
            == "Public verification code used by QR verification."
        )

    def test_override_reason_is_text_field(self):
        assert isinstance(
            model_field(
                FeeClearanceCertificate,
                "override_reason",
            ),
            models.TextField,
        )

    def test_override_reason_default(self):
        field = model_field(
            FeeClearanceCertificate,
            "override_reason",
        )
        assert field.blank is True
        assert field.get_default() == ""

    def test_issued_at_is_optional_and_indexed(self):
        field = model_field(FeeClearanceCertificate, "issued_at")

        assert isinstance(field, models.DateTimeField)
        assert field.null is True
        assert field.blank is True
        assert field.db_index is True


# ---------------------------------------------------------------------------
# Choice behavior
# ---------------------------------------------------------------------------

class TestClearanceStatusChoices:
    @pytest.mark.parametrize(
        ("value", "label"),
        ClearanceStatus.choices,
    )
    def test_display_value(self, value, label):
        certificate = make_certificate(clearance_status=value)
        assert certificate.get_clearance_status_display() == label

    def test_cleared_value(self):
        assert ClearanceStatus.CLEARED == "CLEARED"

    def test_override_value(self):
        assert (
            ClearanceStatus.CLEARED_WITH_OVERRIDE
            == "CLEARED_WITH_OVERRIDE"
        )

    def test_not_cleared_value(self):
        assert ClearanceStatus.NOT_CLEARED == "NOT_CLEARED"


# ---------------------------------------------------------------------------
# Validation: valid states
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateValidStates:
    @pytest.mark.parametrize(
        "status",
        [
            ClearanceStatus.CLEARED,
            ClearanceStatus.NOT_CLEARED,
        ],
    )
    def test_non_override_status_does_not_require_override_fields(
        self,
        status,
    ):
        certificate = make_certificate(
            clearance_status=status,
            override_reason="",
            override_by=None,
        )

        certificate.clean()

    def test_override_status_with_reason_and_user_is_valid(self):
        certificate = make_certificate(
            clearance_status=(
                ClearanceStatus.CLEARED_WITH_OVERRIDE
            ),
            override_reason="Approved hardship arrangement.",
            override_by=make_user(pk=99),
        )

        certificate.clean()

    @pytest.mark.parametrize(
        ("cleared_amount", "balance"),
        [
            (Decimal("0.00"), Decimal("0.00")),
            (Decimal("1.00"), Decimal("0.00")),
            (Decimal("0.00"), Decimal("1.00")),
            (Decimal("1000000.00"), Decimal("25000.50")),
        ],
    )
    def test_non_negative_amounts_are_valid(
        self,
        cleared_amount,
        balance,
    ):
        certificate = make_certificate(
            cleared_amount=cleared_amount,
            outstanding_balance=balance,
        )

        certificate.clean()

    def test_revoked_certificate_with_required_metadata_is_valid(self):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason="Certificate cancelled.",
            revoked_at=timezone.now(),
        )

        certificate.clean()


# ---------------------------------------------------------------------------
# Validation: monetary values
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateMoneyValidation:
    @pytest.mark.parametrize(
        "value",
        [
            Decimal("-0.01"),
            Decimal("-1.00"),
            Decimal("-999999.99"),
        ],
    )
    def test_negative_cleared_amount_is_invalid(self, value):
        certificate = make_certificate(cleared_amount=value)

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "cleared_amount": [
                "Cleared amount cannot be negative."
            ]
        }

    @pytest.mark.parametrize(
        "value",
        [
            Decimal("-0.01"),
            Decimal("-1.00"),
            Decimal("-999999.99"),
        ],
    )
    def test_negative_outstanding_balance_is_invalid(self, value):
        certificate = make_certificate(
            outstanding_balance=value
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "outstanding_balance": [
                "Outstanding balance cannot be negative."
            ]
        }

    def test_both_negative_amount_errors_are_collected(self):
        certificate = make_certificate(
            cleared_amount=Decimal("-1.00"),
            outstanding_balance=Decimal("-2.00"),
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "cleared_amount": [
                "Cleared amount cannot be negative."
            ],
            "outstanding_balance": [
                "Outstanding balance cannot be negative."
            ],
        }


# ---------------------------------------------------------------------------
# Validation: overrides
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateOverrideValidation:
    @pytest.mark.parametrize(
        "reason",
        ["", " ", "   ", "\n", "\t"],
    )
    def test_override_requires_non_blank_reason(self, reason):
        certificate = make_certificate(
            clearance_status=(
                ClearanceStatus.CLEARED_WITH_OVERRIDE
            ),
            override_reason=reason,
            override_by=make_user(pk=88),
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "override_reason": [
                "Override reason is required."
            ]
        }

    def test_override_requires_user(self):
        certificate = make_certificate(
            clearance_status=(
                ClearanceStatus.CLEARED_WITH_OVERRIDE
            ),
            override_reason="Approved by bursar.",
            override_by=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "override_by": [
                "Override user is required."
            ]
        }

    def test_missing_reason_and_user_errors_are_collected(self):
        certificate = make_certificate(
            clearance_status=(
                ClearanceStatus.CLEARED_WITH_OVERRIDE
            ),
            override_reason=" ",
            override_by=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "override_reason": [
                "Override reason is required."
            ],
            "override_by": [
                "Override user is required."
            ],
        }

    def test_override_reason_is_not_required_for_cleared(self):
        certificate = make_certificate(
            clearance_status=ClearanceStatus.CLEARED,
            override_reason="",
            override_by=None,
        )

        certificate.clean()

    def test_override_reason_is_not_required_for_not_cleared(self):
        certificate = make_certificate(
            clearance_status=ClearanceStatus.NOT_CLEARED,
            override_reason="",
            override_by=None,
        )

        certificate.clean()


# ---------------------------------------------------------------------------
# Validation inherited from VersionedModel
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateRevocationValidation:
    def test_revoked_certificate_requires_reason(self):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason=" ",
            revoked_at=timezone.now(),
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "revoked_reason": [
                "A revocation reason is required."
            ]
        }

    def test_revoked_certificate_requires_timestamp(self):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason="Invalid payment record.",
            revoked_at=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert exc_info.value.message_dict == {
            "revoked_at": [
                "A revocation timestamp is required."
            ]
        }

    def test_revocation_errors_are_raised_before_local_errors(self):
        certificate = make_certificate(
            is_revoked=True,
            revoked_reason="",
            revoked_at=None,
            cleared_amount=Decimal("-1.00"),
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.clean()

        assert set(exc_info.value.message_dict) == {
            "revoked_reason",
            "revoked_at",
        }


# ---------------------------------------------------------------------------
# String representation
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateString:
    @pytest.mark.parametrize(
        ("status", "label"),
        ClearanceStatus.choices,
    )
    def test_string_representation(self, status, label):
        certificate = make_certificate(
            certificate_number="FCC-9001",
            student=make_student(
                student_id_number="STU-777",
                name="Alice",
            ),
            clearance_status=status,
        )

        assert str(certificate) == (
            f"FCC-9001 - STU-777 - Alice (Student) "
            f"({label})"
        )

    def test_string_uses_student_profile_string(self):
        student = make_student(
            student_id_number="ASMS-001",
            name="Joseph",
        )
        certificate = make_certificate(student=student)

        assert "ASMS-001 - Joseph (Student)" in str(certificate)


# ---------------------------------------------------------------------------
# Generated artifact and version defaults
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateInheritedDefaults:
    def test_file_is_empty_by_default(self):
        certificate = FeeClearanceCertificate()
        assert not certificate.file

    def test_file_hash_default(self):
        assert FeeClearanceCertificate().file_hash == ""

    def test_file_size_default(self):
        assert FeeClearanceCertificate().file_size is None

    def test_mime_type_default(self):
        assert FeeClearanceCertificate().mime_type == ""

    def test_export_format_default(self):
        assert FeeClearanceCertificate().export_format == ""

    def test_generated_at_default(self):
        assert FeeClearanceCertificate().created_at is None

    def test_failure_message_default(self):
        assert FeeClearanceCertificate().failure_message == ""

    def test_version_default(self):
        assert FeeClearanceCertificate().version == 1

    def test_is_latest_default(self):
        assert FeeClearanceCertificate().is_latest is True

    def test_regeneration_reason_default(self):
        assert FeeClearanceCertificate().regeneration_reason == ""

    def test_is_revoked_default(self):
        assert FeeClearanceCertificate().is_revoked is False

    def test_revoked_reason_default(self):
        assert FeeClearanceCertificate().revoked_reason == ""

    def test_revoked_at_default(self):
        assert FeeClearanceCertificate().revoked_at is None

    def test_root_id_is_generated(self):
        first = FeeClearanceCertificate()
        second = FeeClearanceCertificate()

        assert first.root_id is not None
        assert second.root_id is not None
        assert first.root_id != second.root_id


# ---------------------------------------------------------------------------
# Full clean field-level behavior
# ---------------------------------------------------------------------------

class TestFeeClearanceCertificateFullClean:
    def test_certificate_number_is_required(self):
        certificate = make_certificate(certificate_number="")

        with pytest.raises(ValidationError) as exc_info:
            certificate.full_clean(
                exclude=[
                    "school",
                    "student",
                    "academic_year",
                    "term",
                    "issued_by",
                ],
                validate_unique=False,
                validate_constraints=False,
            )

        assert "certificate_number" in exc_info.value.message_dict

    def test_verification_code_is_required(self):
        certificate = make_certificate(verification_code="")

        with pytest.raises(ValidationError) as exc_info:
            certificate.full_clean(
                exclude=[
                    "school",
                    "student",
                    "academic_year",
                    "term",
                    "issued_by",
                ],
                validate_unique=False,
                validate_constraints=False,
            )

        assert "verification_code" in exc_info.value.message_dict

    def test_clearance_status_is_required(self):
        certificate = make_certificate(clearance_status="")

        with pytest.raises(ValidationError) as exc_info:
            certificate.full_clean(
                exclude=[
                    "school",
                    "student",
                    "academic_year",
                    "term",
                    "issued_by",
                ],
                validate_unique=False,
                validate_constraints=False,
            )

        assert "clearance_status" in exc_info.value.message_dict

    def test_invalid_clearance_status_is_rejected(self):
        certificate = make_certificate(
            clearance_status="UNKNOWN"
        )

        with pytest.raises(ValidationError) as exc_info:
            certificate.full_clean(
                exclude=[
                    "school",
                    "student",
                    "academic_year",
                    "term",
                    "issued_by",
                ],
                validate_unique=False,
                validate_constraints=False,
            )

        assert "clearance_status" in exc_info.value.message_dict