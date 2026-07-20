from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from reports.constants import (
    DocumentType,
    GradingDisplayFormat,
    ReportCategory,
    TemplateEngine,
)
from reports.models.base import (
    AuditableModel,
    SCHOOL_MODEL,
    SchoolScopedModel,
)


class ReportType(models.Model):
    """
    Fixed system catalogue of available report types.

    Examples:
    - student_report_card
    - examination_permit
    - transcript
    - fee_clearance_certificate

    Report types are global and are not created separately by each school.
    """

    code = models.SlugField(
        max_length=64,
        unique=True,
    )
    name = models.CharField(
        max_length=150,
    )
    category = models.CharField(
        max_length=20,
        choices=ReportCategory.choices,
        db_index=True,
    )
    description = models.TextField(
        blank=True,
        default="",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = ["category", "name"]
        indexes = [
            models.Index(
                fields=["category", "is_active"],
                name="reporttype_category_active_idx",
            ),
        ]

    def __str__(self):
        return self.name


class ReportTemplate(SchoolScopedModel, AuditableModel):
    """
    Rendering configuration for a report or document.

    A template may either:

    1. Belong to a specific school, or
    2. Be a system-default template with no school.

    School-specific templates must never be accessed using a client-supplied
    school identifier. Selectors and services must always scope access using
    the authenticated user's school.

    System-default templates act as fallbacks when a school has not configured
    its own template for the requested document type.
    """

    # Override SchoolScopedModel.school because templates may be global
    # system defaults when is_system_default=True.
    school = models.ForeignKey(
        SCHOOL_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        null=True,
        blank=True,
    )

    report_type = models.ForeignKey(
        ReportType,
        on_delete=models.PROTECT,
        related_name="templates",
        null=True,
        blank=True,
    )

    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        db_index=True,
    )

    template_engine = models.CharField(
        max_length=10,
        choices=TemplateEngine.choices,
        default=TemplateEngine.HTML,
    )

    branding = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Branding configuration such as logo, colors, letterhead image, "
            "background image, watermark text or image, font family, and "
            "base font size."
        ),
    )

    page_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Page configuration such as page size, orientation, and margins "
            "{top, bottom, left, right}."
        ),
    )

    placement_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Placement configuration such as logo position, signature "
            "position, and stamp position."
        ),
    )

    grading_display_format = models.CharField(
        max_length=20,
        choices=GradingDisplayFormat.choices,
        default=GradingDisplayFormat.LETTER,
    )

    layout_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Additional layout configuration used by the rendering service."
        ),
    )

    version = models.PositiveIntegerField(
        default=1,
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    is_default = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Marks the active default template for a school and document type."
        ),
    )

    is_system_default = models.BooleanField(
        default=False,
        db_index=True,
    )

    preview_image = models.ImageField(
        upload_to="reports/template_previews/",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "document_type",
            "-is_default",
            "-is_active",
            "-version",
        ]

        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(school__isnull=False)
                    | Q(is_system_default=True)
                ),
                name="reporttemplate_school_or_system_default",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_system_default=False)
                    | Q(school__isnull=True)
                ),
                name="reporttemplate_system_default_has_no_school",
            ),
            models.UniqueConstraint(
                fields=[
                    "school",
                    "document_type",
                    "version",
                ],
                condition=Q(school__isnull=False),
                name="unique_school_document_template_version",
            ),
            models.UniqueConstraint(
                fields=[
                    "document_type",
                    "version",
                ],
                condition=Q(
                    is_system_default=True,
                    school__isnull=True,
                ),
                name="unique_system_document_template_version",
            ),
            models.UniqueConstraint(
                fields=[
                    "school",
                    "document_type",
                ],
                condition=Q(
                    is_default=True,
                    is_active=True,
                    school__isnull=False,
                ),
                name="unique_active_school_default_template",
            ),
            models.UniqueConstraint(
                fields=[
                    "document_type",
                ],
                condition=Q(
                    is_default=True,
                    is_active=True,
                    is_system_default=True,
                    school__isnull=True,
                ),
                name="unique_active_system_default_template",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "school",
                    "document_type",
                    "is_active",
                ],
                name="rpttpl_school_doc_idx",
            ),
            models.Index(
                fields=[
                    "document_type",
                    "is_system_default",
                    "is_active",
                ],
                name="rpttpl_fallback_idx",
            ),
            models.Index(
                fields=[
                    "report_type",
                    "is_active",
                ],
                name="reporttemplate_type_active_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.school_id is None and not self.is_system_default:
            errors["school"] = (
                "A report template must belong to a school unless it is "
                "a system-default template."
            )

        if self.school_id is not None and self.is_system_default:
            errors["is_system_default"] = (
                "A system-default template cannot belong to a school."
            )

        if self.is_default and not self.is_active:
            errors["is_default"] = (
                "An inactive template cannot be marked as the default."
            )

        if self.version < 1:
            errors["version"] = (
                "Template version must be at least 1."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        owner = (
            "SYSTEM"
            if self.is_system_default
            else getattr(self.school, "name", f"school:{self.school_id}")
        )

        return (
            f"{owner} - "
            f"{self.get_document_type_display()} "
            f"(v{self.version})"
        )