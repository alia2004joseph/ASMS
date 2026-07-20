import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import F, Q

from reports.constants import DocumentType
from reports.models.base import (
    AuditableModel,
    SCHOOL_MODEL,
    SchoolScopedModel,
)


def _safe_image_extension(filename):
    """
    Return a normalized image extension while avoiding storage of the
    original filename.
    """
    return Path(filename).suffix.lower()


def _signature_upload_path(instance, filename):
    """
    Store signatures under the owning school's directory.

    Supports both AuthorizedSignatory and DigitalSignature instances.
    """
    school_id = getattr(instance, "school_id", None)

    if school_id is None and getattr(instance, "signatory_id", None):
        school_id = instance.signatory.school_id

    school_id = school_id or "unscoped"
    extension = _safe_image_extension(filename)

    return (
        f"reports/{school_id}/signatures/"
        f"{uuid.uuid4().hex}{extension}"
    )


def _stamp_upload_path(instance, filename):
    school_id = getattr(instance, "school_id", None) or "unscoped"
    extension = _safe_image_extension(filename)

    return (
        f"reports/{school_id}/stamps/"
        f"{uuid.uuid4().hex}{extension}"
    )


class AuthorizedSignatory(SchoolScopedModel, AuditableModel):
    """
    A person authorized by a school to sign official documents.

    The linked user is optional because some signatories, such as external
    registrars or board officials, may not have an ASMS user account.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_signatory_profiles",
        help_text=(
            "Optional ASMS user account associated with this signatory."
        ),
    )

    full_name = models.CharField(
        max_length=150,
    )

    title = models.CharField(
        max_length=150,
        help_text="Official title, such as Head Teacher or Registrar.",
    )

    signature_image = models.ImageField(
        upload_to=_signature_upload_path,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["png", "jpg", "jpeg", "webp"]
            )
        ],
        help_text=(
            "Default signature image used when an assignment does not select "
            "a specific DigitalSignature asset."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    valid_from = models.DateField(
        null=True,
        blank=True,
    )

    valid_until = models.DateField(
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Authorized signatory"
        verbose_name_plural = "Authorized signatories"
        ordering = ["full_name", "title"]

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(valid_from__isnull=True)
                    | Q(valid_until__isnull=True)
                    | Q(valid_until__gte=F("valid_from"))
                ),
                name="signatory_valid_until_after_from",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "is_active"],
                name="signatory_school_active_idx",
            ),
            models.Index(
                fields=["school", "full_name"],
                name="signatory_school_name_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.valid_from
            and self.valid_until
            and self.valid_until < self.valid_from
        ):
            errors["valid_until"] = (
                "The validity end date cannot be earlier than the start date."
            )

        if self.user_id:
            user_school_id = getattr(self.user, "school_id", None)

            if user_school_id and user_school_id != self.school_id:
                errors["user"] = (
                    "The linked user must belong to the same school as the "
                    "authorized signatory."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.full_name} ({self.title})"


class DigitalSignature(SchoolScopedModel, AuditableModel):
    """
    A signature image asset belonging to an authorized signatory.

    A signatory may have several signature assets, such as scanned,
    transparent-background, or specially approved document signatures.

    Cryptographic fields are reserved for future PKI integration. They must
    not be treated as active cryptographic signing functionality until a
    dedicated signing service is implemented.
    """

    signatory = models.ForeignKey(
        AuthorizedSignatory,
        on_delete=models.PROTECT,
        related_name="signatures",
    )

    name = models.CharField(
        max_length=100,
        default="Default Signature",
    )

    image = models.ImageField(
        upload_to=_signature_upload_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["png", "jpg", "jpeg", "webp"]
            )
        ],
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    is_default = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Marks this as the signatory's preferred signature asset."
        ),
    )

    crypto_public_key_ref = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    crypto_signature_hash = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["signatory", "-is_default", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["signatory"],
                condition=Q(is_default=True, is_active=True),
                name="unique_active_default_signature",
            ),
            models.UniqueConstraint(
                fields=["signatory", "name"],
                name="unique_signature_name_per_signatory",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "signatory", "is_active"],
                name="signature_school_signatory_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.signatory_id
            and self.school_id
            and self.signatory.school_id != self.school_id
        ):
            raise ValidationError(
                {
                    "signatory": (
                        "The signature and signatory must belong to the "
                        "same school."
                    )
                }
            )

        if self.is_default and not self.is_active:
            raise ValidationError(
                {
                    "is_default": (
                        "An inactive signature cannot be marked as default."
                    )
                }
            )

    def __str__(self):
        return f"{self.signatory.full_name} - {self.name}"


class SchoolStamp(SchoolScopedModel, AuditableModel):
    """
    A school stamp, seal, or official emblem that may be applied to generated
    documents.
    """

    name = models.CharField(
        max_length=100,
        default="Official Seal",
    )

    image = models.ImageField(
        upload_to=_stamp_upload_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["png", "jpg", "jpeg", "webp"]
            )
        ],
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    is_default = models.BooleanField(
        default=False,
        db_index=True,
    )

    valid_from = models.DateField(
        null=True,
        blank=True,
    )

    valid_until = models.DateField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-is_default", "name"]

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(valid_from__isnull=True)
                    | Q(valid_until__isnull=True)
                    | Q(valid_until__gte=F("valid_from"))
                ),
                name="school_stamp_valid_until_after_from",
            ),
            models.UniqueConstraint(
                fields=["school"],
                condition=Q(is_default=True, is_active=True),
                name="unique_active_default_school_stamp",
            ),
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_school_stamp_name",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "is_active"],
                name="school_stamp_active_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.valid_from
            and self.valid_until
            and self.valid_until < self.valid_from
        ):
            errors["valid_until"] = (
                "The validity end date cannot be earlier than the start date."
            )

        if self.is_default and not self.is_active:
            errors["is_default"] = (
                "An inactive stamp cannot be marked as default."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.name} (school:{self.school_id})"


class DocumentSignatureAssignment(SchoolScopedModel, AuditableModel):
    """
    Defines which signatory, signature asset, and school stamp should appear
    on a particular document type.

    Position information is stored as structured JSON and interpreted only
    by the document rendering service.

    Example:

        {
            "signature": {"zone": "bottom_right"},
            "stamp": {"x": 400, "y": 720},
            "signatory_name": {"zone": "bottom_center"}
        }
    """

    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        db_index=True,
    )

    signatory = models.ForeignKey(
        AuthorizedSignatory,
        on_delete=models.PROTECT,
        related_name="assignments",
    )

    signature = models.ForeignKey(
        DigitalSignature,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assignments",
        help_text=(
            "Optional signature asset. When empty, the rendering service "
            "uses the signatory's active default signature or signature_image."
        ),
    )

    stamp = models.ForeignKey(
        SchoolStamp,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signature_assignments",
    )

    position = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured placement configuration containing named zones or "
            "explicit coordinates."
        ),
    )

    display_order = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Controls the order when a document has multiple signatories."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = ["document_type", "display_order"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "document_type", "display_order"],
                condition=Q(is_active=True),
                name="unique_active_doc_signature_order",
            ),
        ]

        indexes = [
            models.Index(
                fields=["school", "document_type", "is_active"],
                name="doc_signature_school_type_idx",
            ),
            models.Index(
                fields=["school", "signatory", "is_active"],
                name="doc_signature_signatory_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.signatory_id
            and self.school_id
            and self.signatory.school_id != self.school_id
        ):
            errors["signatory"] = (
                "The signatory must belong to the assignment's school."
            )

        if self.signature_id:
            if self.signature.signatory_id != self.signatory_id:
                errors["signature"] = (
                    "The selected signature does not belong to the selected "
                    "signatory."
                )
            elif self.signature.school_id != self.school_id:
                errors["signature"] = (
                    "The selected signature must belong to the assignment's "
                    "school."
                )

            if not self.signature.is_active:
                errors["signature"] = (
                    "An inactive signature cannot be assigned to a document."
                )

        if self.stamp_id:
            if self.stamp.school_id != self.school_id:
                errors["stamp"] = (
                    "The selected stamp must belong to the assignment's school."
                )

            if not self.stamp.is_active:
                errors["stamp"] = (
                    "An inactive stamp cannot be assigned to a document."
                )

        if self.signatory_id and not self.signatory.is_active:
            errors["signatory"] = (
                "An inactive signatory cannot be assigned to a document."
            )

        if not isinstance(self.position, dict):
            errors["position"] = (
                "Position configuration must be a JSON object."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.get_document_type_display()} → "
            f"{self.signatory.full_name}"
        )


class SignatureAssignmentHistory(models.Model):
    """
    Immutable audit record for changes to document signature assignments.

    The service layer must create a history record whenever an assignment is
    created, updated, activated, deactivated, or deleted.
    """

    school = models.ForeignKey(
        SCHOOL_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )

    assignment = models.ForeignKey(
        DocumentSignatureAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history",
    )

    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        db_index=True,
    )

    old_assignment = models.JSONField(
        null=True,
        blank=True,
    )

    new_assignment = models.JSONField(
        null=True,
        blank=True,
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signature_assignment_changes",
    )

    changed_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    change_reason = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        ordering = ["-changed_at"]

        indexes = [
            models.Index(
                fields=["school", "document_type", "-changed_at"],
                name="sig_hist_school_doc_idx",
            ),
            models.Index(
                fields=["assignment", "-changed_at"],
                name="sig_hist_assign_idx",
            ),
            models.Index(
                fields=["changed_by", "-changed_at"],
                name="signature_history_user_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_document_type_display()} signature change "
            f"at {self.changed_at:%Y-%m-%d %H:%M}"
        )