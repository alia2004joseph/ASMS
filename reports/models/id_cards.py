from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from reports.constants import IDCardHolderType, IDCardStatus
from reports.models.base import (
    AbstractGeneratedArtifact,
    SchoolScopedModel,
    VersionedModel,
)


class IDCard(
    AbstractGeneratedArtifact,
    VersionedModel,
    SchoolScopedModel,
):
   
    """
    Represents a generated identification card for a student, teacher,
    or staff member.

    A generic relation is used to avoid maintaining separate, nearly
    identical ID-card tables for every holder category.

    Important rules:

    - holder_content_type and holder_object_id are opaque references.
    - The service layer must validate allowed holder models through an
      explicit registry.
    - Holder role information is frozen in role_context at generation time.
    - Emergency contact data must only be included when permitted by the
      school's privacy configuration.
    - Corrections or replacements create a new version instead of silently
      modifying an already-issued card.
    """

    holder_type = models.CharField(
        max_length=10,
        choices=IDCardHolderType.choices,
        db_index=True,
    )

    holder_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="+",
    )

    holder_object_id = models.PositiveBigIntegerField()

    holder = GenericForeignKey(
        "holder_content_type",
        "holder_object_id",
    )

    identification_number = models.CharField(
        max_length=64,
        db_index=True,
        help_text=(
            "The holder's official student, employee, or staff "
            "identification number."
        ),
    )

    holder_name_snapshot = models.CharField(
        max_length=200,
        help_text=(
            "Frozen display name captured when this card version was issued."
        ),
    )

    role_label = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Human-readable role shown on the card, such as Student, "
            "Teacher, Librarian, or Accountant."
        ),
    )

    role_context = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Frozen role-specific information. Examples: "
            "{'classroom': 'Grade 5A'} or "
            "{'department': 'Science Department'}."
        ),
    )

    valid_from = models.DateField(
        db_index=True,
    )

    valid_until = models.DateField(
        db_index=True,
    )

    verification_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text=(
            "Public, non-sequential code used for QR-code verification."
        ),
    )

    emergency_contact = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Optional frozen emergency-contact information. It must only be "
            "populated when the school's expose_emergency_contact_on_id "
            "setting is enabled."
        ),
    )

    card_status = models.CharField(
        max_length=15,
        choices=IDCardStatus.choices,
        default=IDCardStatus.ACTIVE,
        db_index=True,
    )

    revocation_reason = models.TextField(
        blank=True,
        default="",
        help_text="Required when the card is revoked.",
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.CheckConstraint(
                condition=Q(valid_until__gte=F("valid_from")),
                name="id_card_valid_until_after_from",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="id_card_version_gte_1",
            ),
            models.CheckConstraint(
                condition=(
                    Q(card_status=IDCardStatus.REVOKED)
                    & ~Q(revocation_reason="")
                )
                | ~Q(card_status=IDCardStatus.REVOKED),
                name="id_card_revocation_reason_req",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id", "version"],
                name="unique_id_card_chain_version",
            ),
            models.UniqueConstraint(
                fields=["school", "root_id"],
                condition=Q(is_latest=True),
                name="unique_latest_id_card",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "school",
                    "holder_content_type",
                    "holder_object_id",
                ],
                name="id_card_school_holder_idx",
            ),
            models.Index(
                fields=["school", "identification_number"],
                name="id_card_school_ident_idx",
            ),
            models.Index(
                fields=["school", "holder_type", "card_status"],
                name="id_card_type_status_idx",
            ),
            models.Index(
                fields=["school", "valid_until", "card_status"],
                name="id_card_expiry_status_idx",
            ),
            models.Index(
                fields=["root_id", "version"],
                name="id_card_root_version_idx",
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
                "The card expiry date cannot be earlier than its start date."
            )

        if not self.identification_number.strip():
            errors["identification_number"] = (
                "Identification number is required."
            )

        if not self.holder_name_snapshot.strip():
            errors["holder_name_snapshot"] = (
                "A frozen holder name is required."
            )

        if not isinstance(self.role_context, dict):
            errors["role_context"] = (
                "Role context must be stored as a JSON object."
            )

        if (
            self.emergency_contact is not None
            and not isinstance(self.emergency_contact, dict)
        ):
            errors["emergency_contact"] = (
                "Emergency contact must be stored as a JSON object."
            )

        if self.card_status == IDCardStatus.REVOKED:
            if not self.revocation_reason.strip():
                errors["revocation_reason"] = (
                    "A revocation reason is required for a revoked ID card."
                )
        elif self.revocation_reason.strip():
            errors["revocation_reason"] = (
                "A revocation reason should only be recorded for a revoked "
                "ID card."
            )

        if self.holder_content_type_id and self.holder_object_id:
            holder = self.holder

            if holder is None:
                errors["holder_object_id"] = (
                    "The referenced ID-card holder does not exist."
                )
            elif self.school_id:
                holder_school_id = getattr(holder, "school_id", None)

                if (
                    holder_school_id is not None
                    and holder_school_id != self.school_id
                ):
                    errors["holder_object_id"] = (
                        "The holder must belong to the same school as the "
                        "ID card."
                    )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.get_holder_type_display()} ID "
            f"{self.identification_number} — v{self.version}"
        )