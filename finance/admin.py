# finance/admin.py

from django.contrib import admin

from .models import (
    Expense,
    ExpenseCategory,
    FeeCategory,
    FeeStructure,
    FinancialTransaction,
    InvoiceItem,
    Payment,
    PaymentAllocation,
    Receipt,
    StudentInvoice,
)

# NOTE ON STUDENT SEARCH FIELD:
# `student__student_id_number` is used below because StudentProfile has a
# confirmed `student_id_number` field. If that ever changes, replace the
# lookup(s) below with safe fallbacks such as `student__user__email`,
# `student__user__first_name`, `student__user__last_name`.


class SchoolScopedAdminMixin:
    """
    Restricts non-superuser admin users to their own school.

    Assumptions (verify against the real project if these ever change):
    - request.user.is_superuser exists (standard Django).
    - request.user.school_id exists and is null for superusers.
    - `school_lookup` is the ORM path from this admin's model to the
      School row (e.g. "school" for direct FKs, "payment__school" for a
      model reached only through another model).
    """

    school_lookup = "school"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user

        if user.is_superuser:
            return qs

        if not getattr(user, "school_id", None):
            return qs.none()

        return qs.filter(**{f"{self.school_lookup}_id": user.school_id})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        user = request.user

        if not user.is_superuser and getattr(user, "school_id", None):
            related_model = db_field.related_model
            related_field_names = [f.name for f in related_model._meta.get_fields()]

            if related_model.__name__ == "School":
                kwargs["queryset"] = related_model.objects.filter(pk=user.school_id)
            elif "school" in related_field_names:
                kwargs["queryset"] = related_model._default_manager.filter(
                    school_id=user.school_id
                )

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        user = request.user

        if not user.is_superuser and hasattr(obj, "school_id") and not change:
            obj.school = user.school

        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# Fee categories / structures — ordinary CRUD is still safe here; nothing in
# finance/services.py governs these yet.
# ---------------------------------------------------------------------------


@admin.register(FeeCategory)
class FeeCategoryAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ["name", "code", "school", "is_active"]
    list_filter = ["school", "is_active"]
    search_fields = ["name", "code", "school__name"]
    ordering = ["school", "name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["school"]
    list_select_related = ["school"]


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ["name", "code", "school", "is_active"]
    list_filter = ["school", "is_active"]
    search_fields = ["name", "code", "school__name"]
    ordering = ["school", "name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["school"]
    list_select_related = ["school"]


@admin.register(FeeStructure)
class FeeStructureAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        "name",
        "school",
        "academic_term",
        "classroom",
        "fee_category",
        "amount",
        "is_mandatory",
        "is_active",
    ]
    list_filter = ["school", "academic_term", "is_mandatory", "is_active"]
    search_fields = ["name", "school__name", "classroom__name"]
    ordering = ["school", "academic_term", "name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = [
        "school",
        "academic_term",
        "classroom",
        "fee_category",
        "created_by",
    ]
    list_select_related = ["school", "academic_term", "classroom", "fee_category"]


# ---------------------------------------------------------------------------
# Invoice items — snapshot totals on the parent invoice are only ever
# recalculated by finance/services.py. Until that service exists, items must
# not be created, edited, or deleted from Admin at all: any such mutation
# would desynchronize StudentInvoice.subtotal/total_amount from reality.
# A future service-backed workflow can re-enable controlled editing here.
# ---------------------------------------------------------------------------


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    fields = [
        "fee_structure",
        "fee_category",
        "description",
        "quantity",
        "unit_amount",
        "discount_amount",
        "total_amount",
    ]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = [
        "invoice",
        "fee_category",
        "description",
        "quantity",
        "unit_amount",
        "discount_amount",
        "total_amount",
    ]
    list_filter = ["fee_category"]
    search_fields = ["invoice__invoice_number", "description"]
    list_select_related = ["invoice", "fee_structure", "fee_category"]
    readonly_fields = [
        "invoice",
        "fee_structure",
        "fee_category",
        "description",
        "quantity",
        "unit_amount",
        "discount_amount",
        "total_amount",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Student invoices — snapshot fields are read-only always; invoice_number is
# read-only after creation (numbering will be generated by services later);
# paid/cancelled invoices become fully locked; deletion is only ever allowed
# for a draft invoice with zero recorded payments and no allocations.
# ---------------------------------------------------------------------------


LOCKED_INVOICE_STATUSES = {
    StudentInvoice.Status.PAID,
    StudentInvoice.Status.CANCELLED,
}


@admin.register(StudentInvoice)
class StudentInvoiceAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        "invoice_number",
        "student",
        "school",
        "academic_term",
        "status",
        "total_amount",
        "amount_paid",
        "balance",
        "issue_date",
        "due_date",
    ]
    list_filter = ["school", "status", "academic_term"]
    search_fields = [
        "invoice_number",
        "student__student_id_number",  # verify this field still exists
        "student__user__first_name",
        "student__user__last_name",
    ]
    ordering = ["-issue_date", "school"]
    autocomplete_fields = ["school", "student", "academic_term", "created_by"]
    list_select_related = ["school", "student", "student__user", "academic_term"]
    date_hierarchy = "issue_date"
    inlines = [InvoiceItemInline]

    ALWAYS_READONLY = [
        "subtotal",
        "total_amount",
        "amount_paid",
        "balance",
        "created_by",
        "created_at",
        "updated_at",
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.ALWAYS_READONLY)

        if obj is not None:
            # invoice_number is only mutable at creation time; numbering
            # will later be generated/controlled by finance/services.py.
            readonly.append("invoice_number")

            if obj.status in LOCKED_INVOICE_STATUSES:
                readonly += [
                    "school",
                    "student",
                    "academic_term",
                    "issue_date",
                    "due_date",
                    "status",
                    "discount_amount",
                    "adjustment_amount",
                    "notes",
                ]

        return readonly

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return super().has_delete_permission(request, obj)

        if obj.status != StudentInvoice.Status.DRAFT:
            return False

        if obj.amount_paid and obj.amount_paid != 0:
            return False

        if obj.allocations.exists():
            return False

        return super().has_delete_permission(request, obj)


# ---------------------------------------------------------------------------
# Payments — status transitions, reversal, and cancellation belong to
# finance/services.py. Ordinary Admin may still create a PENDING payment
# (model validation still applies), but once a payment leaves PENDING it
# becomes locked here; deletion is never permitted outside PENDING.
# ---------------------------------------------------------------------------


class PaymentAllocationInline(admin.TabularInline):
    """
    Read-only display of a payment's allocations.

    Allocation creation/change/deletion requires transaction.atomic(),
    select_for_update(), unallocated/outstanding-balance validation, invoice
    snapshot recalculation, and FinancialTransaction creation — all of which
    belong in finance/services.py, not Admin.
    """

    model = PaymentAllocation
    extra = 0
    fields = ["invoice", "amount", "allocated_by", "allocated_at"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


LOCKED_PAYMENT_STATUSES = {
    Payment.Status.COMPLETED,
    Payment.Status.CANCELLED,
    Payment.Status.REVERSED,
}


@admin.register(Payment)
class PaymentAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        "payment_reference",
        "student",
        "school",
        "amount",
        "payment_method",
        "status",
        "payment_date",
    ]
    list_filter = ["school", "status", "payment_method"]
    search_fields = [
        "payment_reference",
        "external_reference",
        "student__student_id_number",  # verify this field still exists
        "student__user__first_name",
        "student__user__last_name",
    ]
    ordering = ["-payment_date", "school"]
    autocomplete_fields = ["school", "student", "received_by"]
    list_select_related = ["school", "student", "student__user", "received_by"]
    date_hierarchy = "payment_date"
    inlines = [PaymentAllocationInline]

    ALWAYS_READONLY = ["received_by", "created_at", "updated_at"]
    LOCKED_FIELDS = [
        "school",
        "student",
        "payment_reference",
        "payment_date",
        "amount",
        "payment_method",
        "payment_proof",
        "status",
        "external_reference",
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.ALWAYS_READONLY)

        if obj is not None and obj.status in LOCKED_PAYMENT_STATUSES:
            readonly += self.LOCKED_FIELDS

        return readonly

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status in LOCKED_PAYMENT_STATUSES:
            # Still viewable (view permission), but not editable: returning
            # False here only disables the change form's save behavior;
            # Django still allows the read-only detail/view page.
            return False

        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != Payment.Status.PENDING:
            return False

        return super().has_delete_permission(request, obj)


# ---------------------------------------------------------------------------
# Payment allocations — fully view-only. Creation/change/deletion is
# intentionally unsupported until finance/services.py exists to enforce
# transaction.atomic(), select_for_update(), and balance validation.
# ---------------------------------------------------------------------------


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    school_lookup = "payment__school"

    list_display = ["payment", "invoice", "amount", "allocated_by", "allocated_at"]
    list_filter = ["allocated_at"]
    search_fields = [
        "payment__payment_reference",
        "invoice__invoice_number",
    ]
    list_select_related = ["payment", "invoice", "allocated_by"]
    readonly_fields = ["payment", "invoice", "amount", "allocated_by", "allocated_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Receipts — numbers will be generated by finance/services.py. View-only.
# ---------------------------------------------------------------------------


@admin.register(Receipt)
class ReceiptAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = ["receipt_number", "school", "payment", "issued_at", "issued_by"]
    list_filter = ["school"]
    search_fields = ["receipt_number", "payment__payment_reference"]
    autocomplete_fields = ["school", "payment", "issued_by"]
    list_select_related = ["school", "payment", "issued_by"]
    readonly_fields = [
        "school",
        "payment",
        "receipt_number",
        "issued_at",
        "issued_by",
        "notes",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Expenses — approval must later run through finance/services.py.
# approved_by/approved_at are always read-only in the ordinary form; once an
# expense leaves DRAFT, its substantive fields lock; approved/paid expenses
# cannot be deleted.
# ---------------------------------------------------------------------------


LOCKED_EXPENSE_STATUSES = {
    Expense.Status.SUBMITTED,
    Expense.Status.APPROVED,
    Expense.Status.REJECTED,
    Expense.Status.PAID,
    Expense.Status.CANCELLED,
}

UNDELETABLE_EXPENSE_STATUSES = {
    Expense.Status.APPROVED,
    Expense.Status.PAID,
}


@admin.register(Expense)
class ExpenseAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        "description",
        "school",
        "category",
        "amount",
        "status",
        "expense_date",
        "recorded_by",
        "approved_by",
    ]
    list_filter = ["school", "status", "payment_method"]
    search_fields = ["description", "reference"]
    ordering = ["-expense_date", "school"]
    autocomplete_fields = ["school", "category", "recorded_by", "approved_by"]
    list_select_related = ["school", "category", "recorded_by", "approved_by"]
    date_hierarchy = "expense_date"

    ALWAYS_READONLY = [
        "approved_by",
        "approved_at",
        "recorded_by",
        "created_at",
        "updated_at",
    ]
    LOCKED_FIELDS = [
        "school",
        "category",
        "description",
        "amount",
        "expense_date",
        "payment_method",
        "reference",
        "status",
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.ALWAYS_READONLY)

        if obj is not None and obj.status in LOCKED_EXPENSE_STATUSES:
            readonly += self.LOCKED_FIELDS

        return readonly

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status in UNDELETABLE_EXPENSE_STATUSES:
            return False

        return super().has_delete_permission(request, obj)


# ---------------------------------------------------------------------------
# Financial transactions — append-only audit log, created only by
# finance/services.py. Fully view-only in Admin: add/change/delete disabled,
# every field read-only, but the detail page remains viewable for users with
# view permission (not blocked by has_change_permission = False).
# ---------------------------------------------------------------------------


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        "transaction_type",
        "school",
        "amount",
        "student",
        "invoice",
        "payment",
        "expense",
        "created_at",
    ]
    list_filter = ["school", "transaction_type"]
    search_fields = ["reference", "description"]
    ordering = ["-created_at", "-pk"]
    list_select_related = ["school", "student", "invoice", "payment", "expense", "created_by"]
    date_hierarchy = "created_at"
    readonly_fields = [
        "school",
        "transaction_type",
        "amount",
        "student",
        "invoice",
        "payment",
        "expense",
        "reference",
        "description",
        "metadata",
        "created_by",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Returning False here only disables edits; Django's
        # has_view_permission() checks the 'view'/'change' permissions
        # directly rather than calling this method, so the read-only
        # detail page remains visible to users with view permission.
        return False

    def has_delete_permission(self, request, obj=None):
        return False