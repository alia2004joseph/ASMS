"""Django administration configuration for the Reports module.

The admin is intentionally an operational and audit interface. Report
creation, regeneration, revocation, signing, and bulk processing remain in the
service layer and are not reimplemented as admin actions.
"""

from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet

from reports.models.bulk_jobs import BulkExportArchive, BulkReportItem, BulkReportJob
from reports.models.certificates import Certificate, CertificateTemplate
from reports.models.custom_reports import (
    CustomReportDefinition,
    CustomReportExecution,
    CustomReportField,
    CustomReportFilter,
    CustomReportGroup,
    CustomReportSort,
)
from reports.models.examinations_admin import (
    InvigilatorAssignment,
    SeatAssignment,
    SeatingPlan,
)
from reports.models.fee_clearance import FeeClearanceCertificate
from reports.models.generated_reports import GeneratedReport, ReportExportLog
from reports.models.id_cards import IDCard
from reports.models.performance_history import PerformanceSnapshot
from reports.models.report_definitions import ReportTemplate, ReportType
from reports.models.result_slips import ResultSlip
from reports.models.signatures import (
    AuthorizedSignatory,
    DigitalSignature,
    DocumentSignatureAssignment,
    SchoolStamp,
    SignatureAssignmentHistory,
)
from reports.models.transcripts import TranscriptGPASnapshot, TranscriptRecord


class SchoolScopedAdminMixin:
    """Restrict non-superusers to records belonging to their own school."""

    school_lookup = "school"

    def get_queryset(self, request) -> QuerySet:
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset

        school_id = getattr(request.user, "school_id", None)
        if school_id is None:
            return queryset.none()

        return queryset.filter(**{f"{self.school_lookup}_id": school_id})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if request.user.is_superuser:
            return field

        school_id = getattr(request.user, "school_id", None)
        if school_id is None or field.queryset is None:
            return field

        related_model = db_field.remote_field.model
        if any(model_field.name == "school" for model_field in related_model._meta.fields):
            field.queryset = field.queryset.filter(school_id=school_id)

        return field

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and hasattr(obj, "school_id"):
            school_id = getattr(request.user, "school_id", None)
            if school_id is not None and not obj.school_id:
                obj.school_id = school_id
        super().save_model(request, obj, form, change)


class ReadOnlyAuditAdminMixin:
    """Prevent editing of records that form an immutable audit trail."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class ReadOnlyInlineMixin:
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReportType)
class ReportTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name", "description")
    ordering = ("category", "name")
    list_editable = ("is_active",)
    list_per_page = 50


@admin.register(ReportTemplate)
class ReportTemplateAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "document_type", "report_type", "school", "template_engine",
        "version", "is_default", "is_system_default", "is_active",
    )
    list_filter = (
        "document_type", "template_engine", "grading_display_format",
        "is_default", "is_system_default", "is_active", "school",
    )
    search_fields = ("report_type__code", "report_type__name", "school__name")
    raw_id_fields  = ("school", "report_type", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "report_type", "created_by")
    ordering = ("document_type", "-version")
    date_hierarchy = "created_at"
    list_per_page = 50
    fieldsets = (
        ("Identity", {"fields": ("school", "report_type", "document_type", "template_engine", "version")}),
        ("Rendering", {"fields": ("branding", "page_config", "placement_config", "layout_config", "grading_display_format", "preview_image")}),
        ("Availability", {"fields": ("is_active", "is_default", "is_system_default")}),
        ("Audit", {"fields": ("created_by", "created_at", "updated_at"), "classes": ("collapse",)}),
    )


class CustomReportFieldInline(admin.TabularInline):
    model = CustomReportField
    extra = 0
    fields = ("field_key", "display_label", "data_type", "order", "is_aggregate", "aggregate_function")
    ordering = ("order",)


class CustomReportFilterInline(admin.TabularInline):
    model = CustomReportFilter
    extra = 0
    fields = ("field_key", "operator", "value", "is_date_range")


class CustomReportSortInline(admin.TabularInline):
    model = CustomReportSort
    extra = 0
    fields = ("field_key", "direction", "order")
    ordering = ("order",)


class CustomReportGroupInline(admin.TabularInline):
    model = CustomReportGroup
    extra = 0
    fields = ("field_key", "order", "show_subtotal", "show_grand_total")
    ordering = ("order",)


@admin.register(CustomReportDefinition)
class CustomReportDefinitionAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "data_source_key", "owner", "school", "is_public", "is_active", "updated_at")
    list_filter = ("is_public", "is_active", "data_source_key", "school")
    search_fields = ("name", "description", "data_source_key", "owner__email")
    raw_id_fields  = ("school", "owner", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "owner", "created_by")
    ordering = ("name",)
    date_hierarchy = "created_at"
    inlines = (CustomReportFieldInline, CustomReportFilterInline, CustomReportSortInline, CustomReportGroupInline)
    list_per_page = 50


@admin.register(CustomReportField)
class CustomReportFieldAdmin(admin.ModelAdmin):
    list_display = ("display_label", "field_key", "definition", "data_type", "order", "is_aggregate", "aggregate_function")
    list_filter = ("data_type", "is_aggregate", "aggregate_function")
    search_fields = ("display_label", "field_key", "definition__name")
    raw_id_fields  = ("definition",)
    list_select_related = ("definition",)
    ordering = ("definition", "order")


@admin.register(CustomReportFilter)
class CustomReportFilterAdmin(admin.ModelAdmin):
    list_display = ("field_key", "operator", "definition", "is_date_range")
    list_filter = ("operator", "is_date_range")
    search_fields = ("field_key", "definition__name")
    raw_id_fields  = ("definition",)
    list_select_related = ("definition",)


@admin.register(CustomReportSort)
class CustomReportSortAdmin(admin.ModelAdmin):
    list_display = ("field_key", "direction", "order", "definition")
    list_filter = ("direction",)
    search_fields = ("field_key", "definition__name")
    raw_id_fields  = ("definition",)
    list_select_related = ("definition",)
    ordering = ("definition", "order")


@admin.register(CustomReportGroup)
class CustomReportGroupAdmin(admin.ModelAdmin):
    list_display = ("field_key", "order", "definition", "show_subtotal", "show_grand_total")
    list_filter = ("show_subtotal", "show_grand_total")
    search_fields = ("field_key", "definition__name")
    raw_id_fields  = ("definition",)
    list_select_related = ("definition",)
    ordering = ("definition", "order")


@admin.register(CustomReportExecution)
class CustomReportExecutionAdmin(SchoolScopedAdminMixin, ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = ("definition", "executed_by", "school", "status", "row_count", "executed_at", "generated_report")
    list_filter = ("status", "school", "executed_at")
    search_fields = ("definition__name", "executed_by__email", "generated_report__file_hash")
    readonly_fields = ("school", "definition", "executed_by", "executed_at", "parameters_snapshot", "row_count", "generated_report", "status")
    list_select_related = ("school", "definition", "executed_by", "generated_report")
    date_hierarchy = "executed_at"
    ordering = ("-executed_at",)


class ReportExportLogInline(ReadOnlyInlineMixin, admin.TabularInline):
    model = ReportExportLog
    fields = ("export_format", "downloaded_by", "downloaded_at", "ip_address", "successful", "failure_message")
    readonly_fields = fields
    ordering = ("-downloaded_at",)


@admin.register(GeneratedReport)
class GeneratedReportAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("report_type", "scope", "school", "status", "export_format", "version", "is_latest", "is_revoked", "requested_by", "created_at")
    list_filter = ("status", "export_format", "scope", "is_latest", "is_revoked", "report_type", "school")
    search_fields = ("report_type__code", "report_type__name", "file_hash", "root_id", "requested_by__email")
    raw_id_fields  = ("school", "report_type", "requested_by", "created_by", "previous_version", "revoked_by")
    readonly_fields = ("root_id", "file_hash", "file_size", "mime_type", "created_at", "created_at", "updated_at", "revoked_at")
    list_select_related = ("school", "report_type", "requested_by", "created_by", "previous_version", "revoked_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = (ReportExportLogInline,)
    list_per_page = 50
    fieldsets = (
    (
        "Report",
        {
            "fields": (
                "school",
                "report_type",
                "requested_by",
                "scope",
                "parameters",
            )
        },
    ),
    (
        "Artifact",
        {
            "fields": (
                "file",
                "file_hash",
                "file_size",
                "mime_type",
                "export_format",
                "generated_at",
                "status",
                "failure_message",
            )
        },
    ),
    (
        "Version",
        {
            "fields": (
                "root_id",
                "version",
                "previous_version",
                "is_latest",
                "regeneration_reason",
            )
        },
    ),
    (
        "Revocation",
        {
            "fields": (
                "is_revoked",
                "revoked_reason",
                "revoked_at",
                "revoked_by",
            )
        },
    ),
    (
        "Audit",
        {
            "fields": (
                "created_by",
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        },
    ),
)


@admin.register(ReportExportLog)
class ReportExportLogAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = ("generated_report", "export_format", "downloaded_by", "successful", "ip_address", "downloaded_at")
    list_filter = ("export_format", "successful", "downloaded_at")
    search_fields = ("generated_report__file_hash", "downloaded_by__email", "ip_address", "failure_message")
    readonly_fields = ("generated_report", "export_format", "downloaded_by", "downloaded_at", "ip_address", "user_agent", "successful", "failure_message")
    list_select_related = ("generated_report", "downloaded_by")
    date_hierarchy = "downloaded_at"
    ordering = ("-downloaded_at",)


class BulkReportItemInline(ReadOnlyInlineMixin, admin.TabularInline):
    model = BulkReportItem
    fields = ("target_content_type", "target_object_id", "status", "generated_report", "error_message")
    readonly_fields = fields
    ordering = ("id",)


@admin.register(BulkReportJob)
class BulkReportJobAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "job_type", "school", "requested_by", "status", "progress", "failed_items", "created_at", "finished_at")
    list_filter = ("job_type", "status", "school", "created_at")
    search_fields = ("id", "requested_by__email")
    raw_id_fields  = ("school", "requested_by")
    readonly_fields = ("total_items", "completed_items", "failed_items", "started_at", "finished_at", "created_at", "progress_percentage")
    list_select_related = ("school", "requested_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = (BulkReportItemInline,)

    @admin.display(description="Progress")
    def progress(self, obj):
        return f"{obj.progress_percentage}%"


@admin.register(BulkReportItem)
class BulkReportItemAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = ("id", "job", "target_content_type", "target_object_id", "status", "generated_report")
    list_filter = ("status", "target_content_type")
    search_fields = ("job__id", "target_object_id", "generated_report__file_hash", "error_message")
    readonly_fields = ("job", "target_content_type", "target_object_id", "status", "generated_report", "error_message")
    list_select_related = ("job", "target_content_type", "generated_report")
    ordering = ("id",)


@admin.register(BulkExportArchive)
class BulkExportArchiveAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("job", "school", "status", "file_size", "downloaded_count", "created_at", "expires_at")
    list_filter = ("status", "export_format", "school", "expires_at")
    search_fields = ("job__id", "file_hash")
    raw_id_fields  = ("school", "job")
    readonly_fields = ("manifest", "file_hash", "file_size", "mime_type", "export_format", "created_at", "status", "failure_message", "downloaded_count")
    list_select_related = ("school", "job")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(CertificateTemplate)
class CertificateTemplateAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("certificate_type", "school", "version", "is_active", "updated_at")
    list_filter = ("certificate_type", "is_active", "school")
    search_fields = ("school__name",)
    raw_id_fields  = ("school", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "created_by")
    ordering = ("school", "certificate_type", "-version")


@admin.register(Certificate)
class CertificateAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("serial_number", "student", "certificate_type", "school", "status", "version", "is_latest", "issued_at")
    list_filter = ("certificate_type", "status", "export_format", "is_latest", "is_revoked", "school")
    search_fields = ("serial_number", "verification_code", "student__first_name", "student__last_name", "file_hash")
    raw_id_fields  = ("school", "student", "template", "issued_by", "previous_version", "revoked_by")
    readonly_fields = ("root_id", "file_hash", "file_size", "mime_type", "created_at", "revoked_at")
    list_select_related = ("school", "student", "template", "issued_by")
    date_hierarchy = "issued_at"
    ordering = ("-issued_at",)


@admin.register(FeeClearanceCertificate)
class FeeClearanceCertificateAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("certificate_number", "student", "term", "clearance_status", "outstanding_balance", "school", "status", "version", "issued_at")
    list_filter = ("clearance_status", "status", "export_format", "is_latest", "is_revoked", "academic_year", "term", "school")
    search_fields = ("certificate_number", "verification_code", "student__first_name", "student__last_name", "file_hash")
    raw_id_fields  = ("school", "student", "academic_year", "term", "override_by", "issued_by", "previous_version", "revoked_by")
    readonly_fields = ("root_id", "cleared_amount", "outstanding_balance", "file_hash", "file_size", "mime_type", "created_at", "revoked_at")
    list_select_related = ("school", "student", "academic_year", "term", "override_by", "issued_by")
    date_hierarchy = "issued_at"
    ordering = ("-issued_at",)


@admin.register(IDCard)
class IDCardAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("identification_number", "holder_name_snapshot", "holder_type", "card_status", "school", "valid_from", "valid_until", "version", "is_latest")
    list_filter = ("holder_type", "card_status", "status", "export_format", "is_latest", "is_revoked", "school")
    search_fields = ("identification_number", "holder_name_snapshot", "verification_code", "file_hash")
    raw_id_fields  = ("school", "holder_content_type", "previous_version", "revoked_by")
    readonly_fields = ("root_id", "file_hash", "file_size", "mime_type", "created_at", "revoked_at")
    list_select_related = ("school", "holder_content_type", "previous_version", "revoked_by")
    date_hierarchy = "valid_from"
    ordering = ("-created_at",)


@admin.register(ResultSlip)
class ResultSlipAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("student", "academic_year", "term", "classroom", "pass_fail_status", "aggregate_or_gpa", "position", "school", "status", "version")
    list_filter = ("pass_fail_status", "status", "export_format", "is_latest", "is_revoked", "academic_year", "term", "classroom", "school")
    search_fields = ("verification_code", "student__first_name", "student__last_name", "file_hash")
    raw_id_fields  = ("school", "student", "academic_year", "term", "classroom", "previous_version", "revoked_by")
    readonly_fields = ("root_id", "subjects_snapshot", "aggregate_or_gpa", "position", "class_average", "file_hash", "file_size", "mime_type", "created_at", "revoked_at")
    list_select_related = ("school", "student", "academic_year", "term", "classroom")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


class TranscriptGPASnapshotInline(ReadOnlyInlineMixin, admin.TabularInline):
    model = TranscriptGPASnapshot
    fields = ("sequence_number", "academic_term", "academic_year_snapshot", "term_name_snapshot", "term_gpa", "cumulative_gpa", "credits_attempted", "credits_earned", "computed_at")
    readonly_fields = fields
    ordering = ("sequence_number",)


@admin.register(TranscriptRecord)
class TranscriptRecordAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("student_name_snapshot", "identification_number_snapshot", "is_official", "cumulative_gpa", "credits_earned_total", "school", "status", "version", "is_latest", "issued_at")
    list_filter = ("is_official", "status", "export_format", "is_latest", "is_revoked", "school")
    search_fields = ("student_name_snapshot", "identification_number_snapshot", "verification_code", "student__first_name", "student__last_name", "file_hash")
    raw_id_fields  = ("school", "student", "issued_by", "previous_version", "revoked_by")
    readonly_fields = ("root_id", "cumulative_gpa", "credits_earned_total", "grading_policy_snapshot", "file_hash", "file_size", "mime_type", "created_at", "revoked_at")
    list_select_related = ("school", "student", "issued_by")
    date_hierarchy = "issued_at"
    ordering = ("-issued_at", "-created_at")
    inlines = (TranscriptGPASnapshotInline,)


@admin.register(TranscriptGPASnapshot)
class TranscriptGPASnapshotAdmin(ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = ("transcript", "sequence_number", "academic_term", "term_gpa", "cumulative_gpa", "credits_attempted", "credits_earned", "computed_at")
    list_filter = ("computed_at", "academic_term")
    search_fields = ("transcript__verification_code", "transcript__student_name_snapshot", "academic_year_snapshot", "term_name_snapshot")
    readonly_fields = tuple(field.name for field in TranscriptGPASnapshot._meta.fields)
    list_select_related = ("transcript", "academic_term")
    date_hierarchy = "computed_at"
    ordering = ("transcript", "sequence_number")


@admin.register(PerformanceSnapshot)
class PerformanceSnapshotAdmin(SchoolScopedAdminMixin, ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = ("student", "academic_term", "snapshot_source", "gpa", "aggregate", "class_position", "class_size", "school", "computed_at")
    list_filter = ("snapshot_source", "academic_term", "school", "computed_at")
    search_fields = ("student__first_name", "student__last_name", "computation_reference", "grading_policy_version")
    readonly_fields = tuple(field.name for field in PerformanceSnapshot._meta.fields)
    list_select_related = ("school", "student", "academic_term", "computed_by")
    date_hierarchy = "computed_at"
    ordering = ("-computed_at",)


class SeatAssignmentInline(admin.TabularInline):
    model = SeatAssignment
    extra = 0
    fields = ("student", "seat_number", "subject_or_paper", "status", "special_needs_accommodation")
    raw_id_fields  = ("student",)
    ordering = ("seat_number",)


class InvigilatorAssignmentInline(admin.TabularInline):
    model = InvigilatorAssignment
    extra = 0
    fields = ("staff", "role", "assigned_at")
    raw_id_fields  = ("staff",)
    readonly_fields = ("assigned_at",)


@admin.register(SeatingPlan)
class SeatingPlanAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("room", "exam_date", "start_time", "end_time", "capacity", "school", "created_at")
    list_filter = ("exam_date", "school")
    search_fields = ("room",)
    raw_id_fields  = ("school", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "created_by")
    date_hierarchy = "exam_date"
    ordering = ("-exam_date", "start_time", "room")
    inlines = (SeatAssignmentInline, InvigilatorAssignmentInline)


@admin.register(SeatAssignment)
class SeatAssignmentAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    school_lookup = "seating_plan__school"
    list_display = ("seating_plan", "seat_number", "student", "subject_or_paper", "status")
    list_filter = ("status", "seating_plan__exam_date", "seating_plan__school")
    search_fields = ("seat_number", "subject_or_paper", "student__first_name", "student__last_name")
    raw_id_fields  = ("seating_plan", "student")
    list_select_related = ("seating_plan", "student")
    ordering = ("seating_plan", "seat_number")


@admin.register(InvigilatorAssignment)
class InvigilatorAssignmentAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    school_lookup = "seating_plan__school"
    list_display = ("seating_plan", "staff", "role", "assigned_at")
    list_filter = ("role", "seating_plan__exam_date", "seating_plan__school")
    search_fields = ("staff__email", "staff__first_name", "staff__last_name", "seating_plan__room")
    raw_id_fields  = ("seating_plan", "staff")
    readonly_fields = ("assigned_at",)
    list_select_related = ("seating_plan", "staff")
    date_hierarchy = "assigned_at"


class DigitalSignatureInline(admin.TabularInline):
    model = DigitalSignature
    extra = 0
    fields = ("name", "image", "is_active", "is_default", "crypto_public_key_ref", "crypto_signature_hash")


@admin.register(AuthorizedSignatory)
class AuthorizedSignatoryAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("full_name", "title", "user", "school", "is_active", "valid_from", "valid_until")
    list_filter = ("is_active", "school", "valid_from", "valid_until")
    search_fields = ("full_name", "title", "user__email")
    raw_id_fields  = ("school", "user", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "user", "created_by")
    ordering = ("full_name", "title")
    inlines = (DigitalSignatureInline,)


@admin.register(DigitalSignature)
class DigitalSignatureAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "signatory", "school", "is_default", "is_active", "updated_at")
    list_filter = ("is_default", "is_active", "school")
    search_fields = ("name", "signatory__full_name", "crypto_public_key_ref", "crypto_signature_hash")
    raw_id_fields  = ("school", "signatory", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "signatory", "created_by")
    ordering = ("signatory", "-is_default", "name")


@admin.register(SchoolStamp)
class SchoolStampAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "school", "is_default", "is_active", "valid_from", "valid_until", "updated_at")
    list_filter = ("is_default", "is_active", "school", "valid_from", "valid_until")
    search_fields = ("name", "school__name")
    raw_id_fields  = ("school", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "created_by")
    ordering = ("school", "-is_default", "name")


@admin.register(DocumentSignatureAssignment)
class DocumentSignatureAssignmentAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ("document_type", "signatory", "signature", "stamp", "position", "display_order", "school", "is_active")
    list_filter = ("document_type", "position", "is_active", "school")
    search_fields = ("signatory__full_name", "signature__name", "stamp__name")
    raw_id_fields  = ("school", "signatory", "signature", "stamp", "created_by")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("school", "signatory", "signature", "stamp", "created_by")
    ordering = ("document_type", "display_order")


@admin.register(SignatureAssignmentHistory)
class SignatureAssignmentHistoryAdmin(SchoolScopedAdminMixin, ReadOnlyAuditAdminMixin, admin.ModelAdmin):
    list_display = ("document_type", "assignment", "school", "changed_by", "changed_at")
    list_filter = ("document_type", "school", "changed_at")
    search_fields = ("assignment__signatory__full_name", "changed_by__email", "change_reason")
    readonly_fields = tuple(field.name for field in SignatureAssignmentHistory._meta.fields)
    list_select_related = ("school", "assignment", "changed_by")
    date_hierarchy = "changed_at"
    ordering = ("-changed_at",)