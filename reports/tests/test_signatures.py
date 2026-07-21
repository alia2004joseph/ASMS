import re
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.utils import timezone

from reports.constants import DocumentType
from reports.models import (
    AuthorizedSignatory,
    DigitalSignature,
    DocumentSignatureAssignment,
    SchoolStamp,
    SignatureAssignmentHistory,
)
from reports.models.signatures import (
    _safe_image_extension,
    _signature_upload_path,
    _stamp_upload_path,
)


def first_choice_value(choice_class):
    """Return the stored value of the first available Django choice."""
    return choice_class.choices[0][0]


def make_school(*, school_id=None, name="Test School"):
    """
    Construct an unsaved School instance.

    An unsaved school is enough for model-level tests that do not require
    database constraints.
    """
    school_model = apps.get_model("schools", "School")
    school = school_model()

    if school_id is not None:
        school.pk = school_id

    if hasattr(school, "name"):
        school.name = name

    return school


def make_user(*, user_id=900, school_id=None):
    """
    Construct an unsaved configured user with a usable primary key.

    A primary key is assigned because AuthorizedSignatory.clean() checks
    self.user_id before validating school consistency.
    """
    user_model = AuthorizedSignatory._meta.get_field(
        "user"
    ).remote_field.model

    user = user_model()
    user.pk = user_id

    if hasattr(user, "school_id"):
        user.school_id = school_id

    return user


def make_signatory(
    *,
    signatory_id=100,
    school_id=1,
    full_name="Joseph Alia",
    title="Head Teacher",
    is_active=True,
    **kwargs,
):
    """
    Construct an unsaved signatory with a usable primary key.

    DocumentSignatureAssignment.clean() checks self.signatory_id before
    validating the signatory, so the test object must imitate a saved record.
    """
    signatory = AuthorizedSignatory(
        school_id=school_id,
        full_name=full_name,
        title=title,
        is_active=is_active,
        **kwargs,
    )

    signatory.pk = signatory_id

    return signatory


def make_signature(
    *,
    signature_id=200,
    signatory=None,
    school_id=1,
    name="Official Signature",
    image_name="signature.png",
    is_active=True,
    is_default=False,
    **kwargs,
):
    """
    Construct an unsaved signature with usable relationship IDs.

    Assigning a primary key makes signature_id available when the signature
    is attached to a DocumentSignatureAssignment.
    """
    signatory = signatory or make_signatory(
        school_id=school_id,
    )

    signature = DigitalSignature(
        school_id=school_id,
        signatory=signatory,
        name=name,
        image=SimpleUploadedFile(
            image_name,
            b"fake-image-content",
            content_type="image/png",
        ),
        is_active=is_active,
        is_default=is_default,
        **kwargs,
    )

    signature.pk = signature_id

    return signature


def make_stamp(
    *,
    stamp_id=300,
    school_id=1,
    name="Official Seal",
    image_name="stamp.png",
    is_active=True,
    is_default=False,
    **kwargs,
):
    """
    Construct an unsaved school stamp with a usable primary key.

    The key makes stamp_id available when the object is assigned to a
    DocumentSignatureAssignment.
    """
    stamp = SchoolStamp(
        school_id=school_id,
        name=name,
        image=SimpleUploadedFile(
            image_name,
            b"fake-image-content",
            content_type="image/png",
        ),
        is_active=is_active,
        is_default=is_default,
        **kwargs,
    )

    stamp.pk = stamp_id

    return stamp


def make_assignment(
    *,
    assignment_id=400,
    school_id=1,
    signatory=None,
    signature=None,
    stamp=None,
    document_type=None,
    **kwargs,
):
    """
    Construct an unsaved document-signature assignment.

    All related helpers assign primary keys so the assignment's validation
    branches execute exactly as they would with saved database objects.
    """
    signatory = signatory or make_signatory(
        school_id=school_id,
    )

    assignment = DocumentSignatureAssignment(
        school_id=school_id,
        document_type=(
            document_type
            or first_choice_value(DocumentType)
        ),
        signatory=signatory,
        signature=signature,
        stamp=stamp,
        **kwargs,
    )

    assignment.pk = assignment_id

    return assignment
    


# ============================================================
# Upload helper tests
# ============================================================


class TestSafeImageExtension:
    def test_returns_lowercase_png_extension(self):
        assert _safe_image_extension("SIGNATURE.PNG") == ".png"

    def test_returns_lowercase_jpeg_extension(self):
        assert _safe_image_extension("Photo.JPEG") == ".jpeg"

    def test_returns_lowercase_webp_extension(self):
        assert _safe_image_extension("seal.WeBp") == ".webp"

    def test_preserves_only_final_extension(self):
        assert _safe_image_extension("signature.final.PNG") == ".png"

    def test_returns_empty_string_when_no_extension_exists(self):
        assert _safe_image_extension("signature") == ""

    def test_does_not_return_original_filename(self):
        result = _safe_image_extension("confidential_signature.png")

        assert result == ".png"
        assert "confidential_signature" not in result


class TestSignatureUploadPath:
    def test_path_contains_school_directory(self):
        signatory = make_signatory(school_id=25)

        path = _signature_upload_path(
            signatory,
            "original-signature.png",
        )

        assert path.startswith("reports/25/signatures/")

    def test_path_uses_lowercase_extension(self):
        signatory = make_signatory(school_id=25)

        path = _signature_upload_path(signatory, "SIGNATURE.PNG")

        assert path.endswith(".png")

    def test_path_does_not_expose_original_filename(self):
        signatory = make_signatory(school_id=25)

        path = _signature_upload_path(
            signatory,
            "joseph-private-signature.png",
        )

        assert "joseph-private-signature" not in path

    def test_path_uses_uuid_hex_filename(self):
        signatory = make_signatory(school_id=25)

        path = _signature_upload_path(signatory, "signature.png")
        filename = path.rsplit("/", 1)[-1]

        assert re.fullmatch(r"[0-9a-f]{32}\.png", filename)

    def test_path_is_unique_for_each_call(self):
        signatory = make_signatory(school_id=25)

        first = _signature_upload_path(signatory, "signature.png")
        second = _signature_upload_path(signatory, "signature.png")

        assert first != second

    def test_path_uses_unscoped_fallback(self):
        signatory = make_signatory(school_id=None)

        path = _signature_upload_path(signatory, "signature.png")

        assert path.startswith("reports/unscoped/signatures/")

    def test_digital_signature_path_uses_signatory_school(self):
        signatory = make_signatory(
            signatory_id=77,
            school_id=77,
        )

        signature = make_signature(
            signature_id=207,
            signatory=signatory,
            school_id=None,
        )

        path = _signature_upload_path(
            signature,
            "signature.png",
        )

        assert path.startswith(
            "reports/77/signatures/"
        )

class TestStampUploadPath:
    def test_path_contains_school_directory(self):
        stamp = make_stamp(school_id=15)

        path = _stamp_upload_path(stamp, "school-stamp.png")

        assert path.startswith("reports/15/stamps/")

    def test_path_uses_lowercase_extension(self):
        stamp = make_stamp(school_id=15)

        path = _stamp_upload_path(stamp, "STAMP.WEBP")

        assert path.endswith(".webp")

    def test_path_does_not_expose_original_filename(self):
        stamp = make_stamp(school_id=15)

        path = _stamp_upload_path(
            stamp,
            "makerere-official-seal.png",
        )

        assert "makerere-official-seal" not in path

    def test_path_uses_uuid_hex_filename(self):
        stamp = make_stamp(school_id=15)

        path = _stamp_upload_path(stamp, "stamp.jpg")
        filename = path.rsplit("/", 1)[-1]

        assert re.fullmatch(r"[0-9a-f]{32}\.jpg", filename)

    def test_path_is_unique_for_each_call(self):
        stamp = make_stamp(school_id=15)

        first = _stamp_upload_path(stamp, "stamp.png")
        second = _stamp_upload_path(stamp, "stamp.png")

        assert first != second

    def test_path_uses_unscoped_fallback(self):
        stamp = make_stamp(school_id=None)

        path = _stamp_upload_path(stamp, "stamp.png")

        assert path.startswith("reports/unscoped/stamps/")


# ============================================================
# AuthorizedSignatory tests
# ============================================================


class TestAuthorizedSignatoryDefaults:
    def test_default_values(self):
        signatory = make_signatory()

        assert signatory.user is None
        assert signatory.user_id is None
        assert signatory.signature_image.name is None
        assert signatory.is_active is True
        assert signatory.valid_from is None
        assert signatory.valid_until is None

    def test_string_representation(self):
        signatory = make_signatory(
            full_name="Sarah Namusoke",
            title="Registrar",
        )

        assert str(signatory) == "Sarah Namusoke (Registrar)"

    def test_school_scoped_manager_is_available(self):
        assert hasattr(AuthorizedSignatory.objects, "for_school")

    def test_user_is_optional(self):
        field = AuthorizedSignatory._meta.get_field("user")

        assert field.null is True
        assert field.blank is True

    def test_user_uses_set_null_on_delete(self):
        field = AuthorizedSignatory._meta.get_field("user")

        assert field.remote_field.on_delete is models.SET_NULL

    def test_full_name_max_length(self):
        field = AuthorizedSignatory._meta.get_field("full_name")

        assert field.max_length == 150

    def test_title_max_length(self):
        field = AuthorizedSignatory._meta.get_field("title")

        assert field.max_length == 150

    def test_signature_image_is_optional(self):
        field = AuthorizedSignatory._meta.get_field(
            "signature_image"
        )

        assert field.null is True
        assert field.blank is True

    def test_signature_image_allowed_extensions(self):
        field = AuthorizedSignatory._meta.get_field(
            "signature_image"
        )
        validator = field.validators[0]

        assert set(validator.allowed_extensions) == {
            "png",
            "jpg",
            "jpeg",
            "webp",
        }

    def test_default_ordering(self):
        assert AuthorizedSignatory._meta.ordering == [
            "full_name",
            "title",
        ]

    def test_verbose_names(self):
        assert (
            AuthorizedSignatory._meta.verbose_name
            == "Authorized signatory"
        )
        assert (
            AuthorizedSignatory._meta.verbose_name_plural
            == "Authorized signatories"
        )

    def test_expected_constraint_exists(self):
        names = {
            constraint.name
            for constraint in AuthorizedSignatory._meta.constraints
        }

        assert names == {
            "signatory_valid_until_after_from",
        }

    def test_expected_indexes_exist(self):
        names = {
            index.name
            for index in AuthorizedSignatory._meta.indexes
        }

        assert names == {
            "signatory_school_active_idx",
            "signatory_school_name_idx",
        }


class TestAuthorizedSignatoryValidation:
    def test_missing_validity_dates_are_valid(self):
        signatory = make_signatory(
            valid_from=None,
            valid_until=None,
        )

        assert signatory.clean() is None

    def test_valid_from_without_valid_until_is_valid(self):
        signatory = make_signatory(
            valid_from=date(2026, 1, 1),
            valid_until=None,
        )

        assert signatory.clean() is None

    def test_valid_until_without_valid_from_is_valid(self):
        signatory = make_signatory(
            valid_from=None,
            valid_until=date(2026, 12, 31),
        )

        assert signatory.clean() is None

    def test_equal_validity_dates_are_valid(self):
        signatory = make_signatory(
            valid_from=date(2026, 7, 20),
            valid_until=date(2026, 7, 20),
        )

        assert signatory.clean() is None

    def test_valid_end_date_after_start_date_is_valid(self):
        signatory = make_signatory(
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 12, 31),
        )

        assert signatory.clean() is None

    def test_valid_until_cannot_precede_valid_from(self):
        signatory = make_signatory(
            valid_from=date(2026, 12, 31),
            valid_until=date(2026, 1, 1),
        )

        with pytest.raises(ValidationError) as exc_info:
            signatory.clean()

        assert "valid_until" in exc_info.value.message_dict

    def test_linked_user_from_same_school_is_valid(self):
        user = make_user(user_id=10, school_id=1)

        signatory = make_signatory(
            school_id=1,
            user=user,
        )

        assert signatory.clean() is None

    def test_linked_user_from_different_school_is_invalid(self):
        user = make_user(user_id=10, school_id=2)

        signatory = make_signatory(
            school_id=1,
            user=user,
        )

        with pytest.raises(ValidationError) as exc_info:
            signatory.clean()

        assert "user" in exc_info.value.message_dict

    def test_user_without_school_does_not_fail_validation(self):
        user = make_user(user_id=10, school_id=None)

        signatory = make_signatory(
            school_id=1,
            user=user,
        )

        assert signatory.clean() is None


# ============================================================
# DigitalSignature tests
# ============================================================


class TestDigitalSignatureDefaults:
    def test_default_values(self):
        signature = make_signature(name="Default Signature")

        assert signature.name == "Default Signature"
        assert signature.is_active is True
        assert signature.is_default is False
        assert signature.crypto_public_key_ref is None
        assert signature.crypto_signature_hash is None

    def test_model_field_default_name(self):
        field = DigitalSignature._meta.get_field("name")

        assert field.default == "Default Signature"
        assert field.max_length == 100

    def test_string_representation(self):
        signatory = make_signatory(
            full_name="Joseph Alia",
            title="Head Teacher",
        )
        signature = make_signature(
            signatory=signatory,
            name="Transparent Signature",
        )

        assert str(signature) == (
            "Joseph Alia - Transparent Signature"
        )

    def test_signatory_uses_protect_on_delete(self):
        field = DigitalSignature._meta.get_field("signatory")

        assert field.remote_field.on_delete is models.PROTECT

    def test_image_is_required(self):
        field = DigitalSignature._meta.get_field("image")

        assert field.null is False
        assert field.blank is False

    def test_image_allowed_extensions(self):
        field = DigitalSignature._meta.get_field("image")
        validator = field.validators[0]

        assert set(validator.allowed_extensions) == {
            "png",
            "jpg",
            "jpeg",
            "webp",
        }

    def test_crypto_fields_are_optional(self):
        public_key = DigitalSignature._meta.get_field(
            "crypto_public_key_ref"
        )
        signature_hash = DigitalSignature._meta.get_field(
            "crypto_signature_hash"
        )

        assert public_key.null is True
        assert public_key.blank is True
        assert signature_hash.null is True
        assert signature_hash.blank is True

    def test_crypto_fields_max_length(self):
        public_key = DigitalSignature._meta.get_field(
            "crypto_public_key_ref"
        )
        signature_hash = DigitalSignature._meta.get_field(
            "crypto_signature_hash"
        )

        assert public_key.max_length == 255
        assert signature_hash.max_length == 255

    def test_default_ordering(self):
        assert DigitalSignature._meta.ordering == [
            "signatory",
            "-is_default",
            "name",
        ]

    def test_expected_constraints_exist(self):
        names = {
            constraint.name
            for constraint in DigitalSignature._meta.constraints
        }

        assert names == {
            "unique_active_default_signature",
            "unique_signature_name_per_signatory",
        }

    def test_expected_index_exists(self):
        names = {
            index.name
            for index in DigitalSignature._meta.indexes
        }

        assert names == {
            "signature_school_signatory_idx",
        }

    def test_school_scoped_manager_is_available(self):
        assert hasattr(DigitalSignature.objects, "for_school")


class TestDigitalSignatureValidation:
    def test_matching_school_is_valid(self):
        signatory = make_signatory(school_id=1)
        signature = make_signature(
            signatory=signatory,
            school_id=1,
        )

        assert signature.clean() is None

    def test_signature_and_signatory_school_must_match(self):
        signatory = make_signatory(school_id=2)
        signature = make_signature(
            signatory=signatory,
            school_id=1,
        )

        with pytest.raises(ValidationError) as exc_info:
            signature.clean()

        assert "signatory" in exc_info.value.message_dict

    def test_active_default_signature_is_valid(self):
        signature = make_signature(
            is_active=True,
            is_default=True,
        )

        assert signature.clean() is None

    def test_inactive_non_default_signature_is_valid(self):
        signature = make_signature(
            is_active=False,
            is_default=False,
        )

        assert signature.clean() is None

    def test_inactive_signature_cannot_be_default(self):
        signature = make_signature(
            is_active=False,
            is_default=True,
        )

        with pytest.raises(ValidationError) as exc_info:
            signature.clean()

        assert "is_default" in exc_info.value.message_dict


# ============================================================
# SchoolStamp tests
# ============================================================


class TestSchoolStampDefaults:
    def test_default_values(self):
        stamp = make_stamp()

        assert stamp.name == "Official Seal"
        assert stamp.is_active is True
        assert stamp.is_default is False
        assert stamp.valid_from is None
        assert stamp.valid_until is None

    def test_model_field_default_name(self):
        field = SchoolStamp._meta.get_field("name")

        assert field.default == "Official Seal"
        assert field.max_length == 100

    def test_string_representation(self):
        stamp = make_stamp(
            school_id=40,
            name="Academic Seal",
        )

        assert str(stamp) == "Academic Seal (school:40)"

    def test_image_is_required(self):
        field = SchoolStamp._meta.get_field("image")

        assert field.null is False
        assert field.blank is False

    def test_image_allowed_extensions(self):
        field = SchoolStamp._meta.get_field("image")
        validator = field.validators[0]

        assert set(validator.allowed_extensions) == {
            "png",
            "jpg",
            "jpeg",
            "webp",
        }

    def test_default_ordering(self):
        assert SchoolStamp._meta.ordering == [
            "-is_default",
            "name",
        ]

    def test_expected_constraints_exist(self):
        names = {
            constraint.name
            for constraint in SchoolStamp._meta.constraints
        }

        assert names == {
            "school_stamp_valid_until_after_from",
            "unique_active_default_school_stamp",
            "unique_school_stamp_name",
        }

    def test_expected_index_exists(self):
        names = {
            index.name for index in SchoolStamp._meta.indexes
        }

        assert names == {
            "school_stamp_active_idx",
        }

    def test_school_scoped_manager_is_available(self):
        assert hasattr(SchoolStamp.objects, "for_school")


class TestSchoolStampValidation:
    def test_missing_validity_dates_are_valid(self):
        stamp = make_stamp(
            valid_from=None,
            valid_until=None,
        )

        assert stamp.clean() is None

    def test_equal_validity_dates_are_valid(self):
        stamp = make_stamp(
            valid_from=date(2026, 7, 20),
            valid_until=date(2026, 7, 20),
        )

        assert stamp.clean() is None

    def test_valid_date_range_is_valid(self):
        stamp = make_stamp(
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 12, 31),
        )

        assert stamp.clean() is None

    def test_valid_until_cannot_precede_valid_from(self):
        stamp = make_stamp(
            valid_from=date(2026, 12, 31),
            valid_until=date(2026, 1, 1),
        )

        with pytest.raises(ValidationError) as exc_info:
            stamp.clean()

        assert "valid_until" in exc_info.value.message_dict

    def test_active_default_stamp_is_valid(self):
        stamp = make_stamp(
            is_active=True,
            is_default=True,
        )

        assert stamp.clean() is None

    def test_inactive_non_default_stamp_is_valid(self):
        stamp = make_stamp(
            is_active=False,
            is_default=False,
        )

        assert stamp.clean() is None

    def test_inactive_stamp_cannot_be_default(self):
        stamp = make_stamp(
            is_active=False,
            is_default=True,
        )

        with pytest.raises(ValidationError) as exc_info:
            stamp.clean()

        assert "is_default" in exc_info.value.message_dict

    def test_validation_collects_date_and_default_errors(self):
        stamp = make_stamp(
            valid_from=date(2026, 12, 31),
            valid_until=date(2026, 1, 1),
            is_active=False,
            is_default=True,
        )

        with pytest.raises(ValidationError) as exc_info:
            stamp.clean()

        errors = exc_info.value.message_dict

        assert "valid_until" in errors
        assert "is_default" in errors


# ============================================================
# DocumentSignatureAssignment tests
# ============================================================


class TestDocumentSignatureAssignmentDefaults:
    def test_default_values(self):
        assignment = make_assignment()

        assert assignment.signature is None
        assert assignment.signature_id is None
        assert assignment.stamp is None
        assert assignment.stamp_id is None
        assert assignment.position == {}
        assert assignment.display_order == 0
        assert assignment.is_active is True

    def test_position_default_is_not_shared(self):
        first = make_assignment()
        second = make_assignment()

        first.position["signature"] = {
            "zone": "bottom_right",
        }

        assert second.position == {}

    def test_string_representation(self):
        signatory = make_signatory(
            full_name="Sarah Namusoke",
            title="Registrar",
        )
        assignment = make_assignment(signatory=signatory)

        assert str(assignment) == (
            f"{assignment.get_document_type_display()} "
            "→ Sarah Namusoke"
        )

    def test_document_type_uses_expected_choices(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "document_type"
        )

        assert list(field.choices) == list(DocumentType.choices)
        assert field.db_index is True

    def test_signatory_uses_protect_on_delete(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "signatory"
        )

        assert field.remote_field.on_delete is models.PROTECT

    def test_signature_is_optional(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "signature"
        )

        assert field.null is True
        assert field.blank is True

    def test_signature_uses_protect_on_delete(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "signature"
        )

        assert field.remote_field.on_delete is models.PROTECT

    def test_stamp_is_optional(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "stamp"
        )

        assert field.null is True
        assert field.blank is True

    def test_stamp_uses_protect_on_delete(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "stamp"
        )

        assert field.remote_field.on_delete is models.PROTECT

    def test_position_is_json_field(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "position"
        )

        assert isinstance(field, models.JSONField)

    def test_display_order_is_positive_integer(self):
        field = DocumentSignatureAssignment._meta.get_field(
            "display_order"
        )

        assert isinstance(field, models.PositiveIntegerField)

    def test_default_ordering(self):
        assert DocumentSignatureAssignment._meta.ordering == [
            "document_type",
            "display_order",
        ]

    def test_expected_constraint_exists(self):
        names = {
            constraint.name
            for constraint
            in DocumentSignatureAssignment._meta.constraints
        }

        assert names == {
            "unique_active_doc_signature_order",
        }

    def test_expected_indexes_exist(self):
        names = {
            index.name
            for index in DocumentSignatureAssignment._meta.indexes
        }

        assert names == {
            "doc_signature_school_type_idx",
            "doc_signature_signatory_idx",
        }

    def test_school_scoped_manager_is_available(self):
        assert hasattr(
            DocumentSignatureAssignment.objects,
            "for_school",
        )


class TestDocumentSignatureAssignmentValidation:
    def test_valid_assignment_without_optional_assets(self):
        assignment = make_assignment()

        assert assignment.clean() is None

    def test_valid_assignment_with_signature_and_stamp(self):
        signatory = make_signatory(school_id=1)
        signature = make_signature(
            school_id=1,
            signatory=signatory,
            is_active=True,
        )
        stamp = make_stamp(
            school_id=1,
            is_active=True,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=signatory,
            signature=signature,
            stamp=stamp,
            position={"signature": {"zone": "bottom_right"}},
        )

        assert assignment.clean() is None

    def test_signatory_must_belong_to_assignment_school(self):
        signatory = make_signatory(school_id=2)

        assignment = make_assignment(
            school_id=1,
            signatory=signatory,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "signatory" in exc_info.value.message_dict

    def test_signature_must_belong_to_selected_signatory(self):
        selected_signatory = make_signatory(
        signatory_id=112,
        school_id=1,
        full_name="Selected Signatory",
    )
        different_signatory = make_signatory(
            signatory_id=113,
            school_id=1,
            full_name="Different Signatory",
        )

        signature = make_signature(
            signature_id=211,
            school_id=1,
            signatory=different_signatory,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=selected_signatory,
            signature=signature,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "signature" in exc_info.value.message_dict

    def test_signature_must_belong_to_assignment_school(self):
        signatory = make_signatory(school_id=1)
        signatory.pk = 10

        signature = make_signature(
            school_id=2,
            signatory=signatory,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=signatory,
            signature=signature,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "signature" in exc_info.value.message_dict

    def test_inactive_signature_cannot_be_assigned(self):
        signatory = make_signatory(school_id=1)
        signatory.pk = 10

        signature = make_signature(
            school_id=1,
            signatory=signatory,
            is_active=False,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=signatory,
            signature=signature,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "signature" in exc_info.value.message_dict

    def test_stamp_must_belong_to_assignment_school(self):
        signatory = make_signatory(school_id=1)
        stamp = make_stamp(
            school_id=2,
            is_active=True,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=signatory,
            stamp=stamp,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "stamp" in exc_info.value.message_dict

    def test_inactive_stamp_cannot_be_assigned(self):
        signatory = make_signatory(school_id=1)
        stamp = make_stamp(
            school_id=1,
            is_active=False,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=signatory,
            stamp=stamp,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "stamp" in exc_info.value.message_dict

    def test_inactive_signatory_cannot_be_assigned(self):
        signatory = make_signatory(
            school_id=1,
            is_active=False,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=signatory,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "signatory" in exc_info.value.message_dict

    @pytest.mark.parametrize(
        "invalid_position",
        [
            [],
            "bottom-right",
            25,
            True,
            ("bottom", "right"),
        ],
    )
    def test_position_must_be_json_object(
        self,
        invalid_position,
    ):
        assignment = make_assignment(
            position=invalid_position,
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        assert "position" in exc_info.value.message_dict

    def test_empty_position_dictionary_is_valid(self):
        assignment = make_assignment(position={})

        assert assignment.clean() is None

    def test_nested_position_dictionary_is_valid(self):
        assignment = make_assignment(
            position={
                "signature": {
                    "zone": "bottom_right",
                },
                "stamp": {
                    "x": 400,
                    "y": 720,
                },
            }
        )

        assert assignment.clean() is None

    def test_validation_collects_multiple_assignment_errors(self):
        inactive_signatory = make_signatory(
            signatory_id=119,
            school_id=2,
            is_active=False,
        )

        inactive_stamp = make_stamp(
            stamp_id=313,
            school_id=3,
            is_active=False,
        )

        assignment = make_assignment(
            school_id=1,
            signatory=inactive_signatory,
            stamp=inactive_stamp,
            position=[],
        )

        with pytest.raises(ValidationError) as exc_info:
            assignment.clean()

        errors = exc_info.value.message_dict

        assert "signatory" in errors
        assert "stamp" in errors
        assert "position" in errors


# ============================================================
# SignatureAssignmentHistory tests
# ============================================================


class TestSignatureAssignmentHistory:
    def test_default_values(self):
        history = SignatureAssignmentHistory(
            school_id=1,
            document_type=first_choice_value(DocumentType),
        )

        assert history.assignment is None
        assert history.assignment_id is None
        assert history.old_assignment is None
        assert history.new_assignment is None
        assert history.changed_by is None
        assert history.changed_by_id is None
        assert history.change_reason == ""

    def test_school_is_required(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "school"
        )

        assert field.null is False
        assert field.blank is False

    def test_school_uses_protect_on_delete(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "school"
        )

        assert field.remote_field.on_delete is models.PROTECT

    def test_assignment_is_optional(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "assignment"
        )

        assert field.null is True
        assert field.blank is True

    def test_assignment_uses_set_null_on_delete(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "assignment"
        )

        assert field.remote_field.on_delete is models.SET_NULL

    def test_changed_by_is_optional(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "changed_by"
        )

        assert field.null is True
        assert field.blank is True

    def test_changed_by_uses_set_null_on_delete(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "changed_by"
        )

        assert field.remote_field.on_delete is models.SET_NULL

    def test_document_type_uses_expected_choices(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "document_type"
        )

        assert list(field.choices) == list(DocumentType.choices)
        assert field.db_index is True

    def test_old_and_new_assignments_are_optional_json_fields(self):
        old_field = SignatureAssignmentHistory._meta.get_field(
            "old_assignment"
        )
        new_field = SignatureAssignmentHistory._meta.get_field(
            "new_assignment"
        )

        assert isinstance(old_field, models.JSONField)
        assert old_field.null is True
        assert old_field.blank is True

        assert isinstance(new_field, models.JSONField)
        assert new_field.null is True
        assert new_field.blank is True

    def test_changed_at_uses_auto_now_add(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "changed_at"
        )

        assert field.auto_now_add is True
        assert field.db_index is True

    def test_change_reason_defaults_to_empty_string(self):
        field = SignatureAssignmentHistory._meta.get_field(
            "change_reason"
        )

        assert field.default == ""
        assert field.blank is True

    def test_default_ordering(self):
        assert SignatureAssignmentHistory._meta.ordering == [
            "-changed_at"
        ]

    def test_expected_indexes_exist(self):
        names = {
            index.name
            for index in SignatureAssignmentHistory._meta.indexes
        }

        assert names == {
            "sig_hist_school_doc_idx",
            "sig_hist_assign_idx",
            "signature_history_user_idx",
        }

    def test_string_representation(self):
        changed_at = timezone.make_aware(
            datetime(2026, 7, 20, 14, 30)
        )

        history = SignatureAssignmentHistory(
            school_id=1,
            document_type=first_choice_value(DocumentType),
            changed_at=changed_at,
        )

        assert str(history) == (
            f"{history.get_document_type_display()} "
            "signature change at 2026-07-20 14:30"
        )