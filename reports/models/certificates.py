from django.conf import settings
from django.db import models


from reports.models.base import (
    AbstractGeneratedArtifact,
    AuditableModel,
    SchoolScopedModel,
    VersionedModel,
)


class CertificateTemplate(SchoolScopedModel, AuditableModel):
    CERTIFICATE_TYPES = [
        ("COMPLETION", "Certificate of Completion"),
        ("PARTICIPATION", "Certificate of Participation"),
        ("GRADUATION", "Graduation Certificate"),
        ("TESTIMONIAL", "Testimonial"),
    ]

    certificate_type = models.CharField(
        max_length=20,
        choices=CERTIFICATE_TYPES,
    )

    layout_config = models.JSONField(
        default=dict,
        blank=True,
    )

    branding = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Branding configuration for this certificate template: logo, "
            "colors, motto, letterhead/background/watermark images, font "
            "family, and security microtext. Falls back to sensible "
            "defaults when a field is not configured."
        ),
    )

    signature_fields = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Which signatory roles appear on this certificate type, "
            "for example: {'primary': 'Head Teacher', "
            "'secondary': 'Registrar'}"
        ),
    )

    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [
            models.Index(
                fields=["school", "certificate_type", "is_active"]
            )
        ]

    def __str__(self):
        return (
            f"{self.get_certificate_type_display()} template "
            f"({self.school_id})"
        )




class CertificateNumberSequence(SchoolScopedModel):
    """
    Maintains a safe school-specific certificate sequence.

    A separate sequence is maintained for every school, year,
    and certificate type.
    """

    year = models.PositiveIntegerField()

    certificate_type = models.CharField(
        max_length=20,
        choices=CertificateTemplate.CERTIFICATE_TYPES,
    )

    last_number = models.PositiveBigIntegerField(
        default=0,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "school",
                    "year",
                    "certificate_type",
                ],
                name="unique_certificate_number_sequence",
            ),
        ]

    def __str__(self):
        return (
            f"{self.school.code}-{self.year}-"
            f"{self.certificate_type}: {self.last_number}"
        )

class Certificate(
    AbstractGeneratedArtifact,
    VersionedModel,
    SchoolScopedModel,
):
    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="certificates",
    )

    certificate_type = models.CharField(
        max_length=20,
        choices=CertificateTemplate.CERTIFICATE_TYPES,
    )

    template = models.ForeignKey(
        CertificateTemplate,
        on_delete=models.PROTECT,
        related_name="certificates",
    )

    serial_number = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )

    verification_code = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    issued_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["school", "student", "certificate_type"]
            ),
            models.Index(
                fields=["root_id", "version"]
            ),
        ]

    def __str__(self):
        return (
            f"{self.certificate_type} certificate "
            f"#{self.serial_number}"
        )