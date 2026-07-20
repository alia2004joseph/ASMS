# finance/models.py

import os
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import User
from academics.models import AcademicTerm, Classroom

ZERO = Decimal("0.00")
MIN_POSITIVE = Decimal("0.01")


def _norm(value):
    """Trim surrounding whitespace; keep blank strings as '' (never None)."""
    if value is None:
        return value
    return value.strip()


def payment_proof_upload_path(instance, filename):
    """
    Organize uploaded payment proofs by school and year.

    The original filename is not trusted; a random name is generated and
    only the extension is preserved. File type/size validation belongs in
    the serializer, not here.
    """
    _, ext = os.path.splitext(filename)
    school_id = instance.school_id or "unknown"
    year = timezone.now().year
    return f"payment_proofs/{school_id}/{year}/{uuid.uuid4().hex}{ext.lower()}"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    BANK_TRANSFER = "bank_transfer", "Bank Transfer"
    MOBILE_MONEY = "mobile_money", "Mobile Money"
    CHEQUE = "cheque", "Cheque"
    CARD = "card", "Card"
    OTHER = "other", "Other"


class FeeCategory(models.Model):
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="fee_categories",
        verbose_name="School",
    )
    name = models.CharField(max_length=100, verbose_name="Name")
    code = models.CharField(max_length=30, verbose_name="Code")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Is Active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fee Category"
        verbose_name_plural = "Fee Categories"
        ordering = ["school", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_fee_category_name_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "code"],
                name="unique_fee_category_code_per_school",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.school})"

    def clean(self):
        self.name = _norm(self.name)
        self.code = _norm(self.code)
        self.description = _norm(self.description) or ""

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ExpenseCategory(models.Model):
    """
    A classification for operational expenses.

    Kept separate from FeeCategory because fee categories describe what a
    school charges students, while expense categories describe what a
    school spends money on; conflating the two would blur reporting and
    would let a fee-facing category accidentally apply to expenses.
    """

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="expense_categories",
        verbose_name="School",
    )
    name = models.CharField(max_length=100, verbose_name="Name")
    code = models.CharField(max_length=30, verbose_name="Code")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Is Active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Expense Category"
        verbose_name_plural = "Expense Categories"
        ordering = ["school", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_expense_category_name_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "code"],
                name="unique_expense_category_code_per_school",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.school})"

    def clean(self):
        self.name = _norm(self.name)
        self.code = _norm(self.code)
        self.description = _norm(self.description) or ""

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class FeeStructure(models.Model):
    """A fee charged to a classroom (or the whole school) for a term."""

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="fee_structures",
        verbose_name="School",
    )
    academic_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.PROTECT,
        related_name="fee_structures",
        verbose_name="Academic Term",
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.PROTECT,
        related_name="fee_structures",
        null=True,
        blank=True,
        verbose_name="Classroom",
        help_text="Leave blank to apply this fee to the whole school.",
    )
    fee_category = models.ForeignKey(
        FeeCategory,
        on_delete=models.PROTECT,
        related_name="fee_structures",
        verbose_name="Fee Category",
    )
    name = models.CharField(max_length=150, verbose_name="Name")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(MIN_POSITIVE)],
        verbose_name="Amount",
    )
    due_date = models.DateField(null=True, blank=True, verbose_name="Due Date")
    is_mandatory = models.BooleanField(default=True, verbose_name="Is Mandatory")
    is_active = models.BooleanField(default=True, verbose_name="Is Active")
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_fee_structures",
        verbose_name="Created By",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fee Structure"
        verbose_name_plural = "Fee Structures"
        ordering = ["school", "academic_term", "name"]
        constraints = [
            # NULL is never equal to NULL in PostgreSQL, so a plain unique
            # constraint on (school, academic_term, classroom, fee_category,
            # name) would silently allow unlimited duplicate school-wide
            # (classroom=NULL) fee structures. Two partial constraints
            # close that gap: one for classroom-specific rows, one for
            # school-wide rows using a fixed sentinel condition instead of
            # relying on NULL equality.
            models.UniqueConstraint(
                fields=["school", "academic_term", "classroom", "fee_category", "name"],
                condition=models.Q(is_active=True, classroom__isnull=False),
                name="unique_active_fee_structure_per_classroom",
            ),
            models.UniqueConstraint(
                fields=["school", "academic_term", "fee_category", "name"],
                condition=models.Q(is_active=True, classroom__isnull=True),
                name="unique_active_school_wide_fee_structure",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=ZERO),
                name="fee_structure_amount_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "academic_term"]),
            models.Index(fields=["school", "classroom"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.academic_term} ({self.school})"

    def clean(self):
        self.name = _norm(self.name)
        errors = {}

        if self.academic_term_id and self.academic_term.school_id != self.school_id:
            errors["academic_term"] = "The academic term must belong to the same school."

        if self.classroom_id and self.classroom.school_id != self.school_id:
            errors["classroom"] = "The classroom must belong to the same school."

        if self.fee_category_id and self.fee_category.school_id != self.school_id:
            errors["fee_category"] = "The fee category must belong to the same school."

        if self.created_by_id and not self.created_by.is_superuser:
            if self.created_by.school_id != self.school_id:
                errors["created_by"] = "The creator must belong to the same school."

        if self.amount is not None and self.amount <= ZERO:
            errors["amount"] = "Amount must be greater than zero."

        if (
            self.due_date
            and self.academic_term_id
            and self.academic_term.start_date
            and self.academic_term.end_date
            and not (self.academic_term.start_date <= self.due_date <= self.academic_term.end_date)
        ):
            errors["due_date"] = "The due date should fall within the academic term."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class StudentInvoice(models.Model):
    """
    Represents a student's invoice for a term.

    IMPORTANT — denormalized snapshot fields:
    subtotal, discount_amount, adjustment_amount, total_amount, amount_paid
    and balance are stored financial snapshots, not live-computed values.
    They exist so reporting and display do not need to re-aggregate items
    and allocations on every read. This model intentionally does NOT
    recalculate them in clean() or save(); only finance/services.py may
    recompute and persist them, inside a transaction, after items or
    allocations change. clean() only rejects obviously invalid states.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name="School",
    )
    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name="Student",
    )
    academic_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name="Academic Term",
    )
    invoice_number = models.CharField(max_length=50, verbose_name="Invoice Number")
    issue_date = models.DateField(verbose_name="Issue Date")
    due_date = models.DateField(null=True, blank=True, verbose_name="Due Date")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Status",
    )

    # --- Denormalized financial snapshot fields (see docstring above) ---
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Subtotal",
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Discount Amount",
    )
    adjustment_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        verbose_name="Adjustment Amount",
        help_text="Positive to add, negative to subtract from the total.",
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Total Amount",
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Amount Paid",
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Balance",
    )
    # --- end snapshot fields ---

    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_invoices",
        verbose_name="Created By",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Student Invoice"
        verbose_name_plural = "Student Invoices"
        ordering = ["-issue_date", "school"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "invoice_number"],
                name="unique_invoice_number_per_school",
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=ZERO),
                name="invoice_subtotal_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=ZERO),
                name="invoice_discount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=ZERO),
                name="invoice_total_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_paid__gte=ZERO),
                name="invoice_amount_paid_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(balance__gte=ZERO),
                name="invoice_balance_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "status"]),
            models.Index(fields=["student", "status"]),
            models.Index(fields=["school", "academic_term"]),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.student} ({self.school})"

    def clean(self):
        self.invoice_number = _norm(self.invoice_number)
        self.notes = _norm(self.notes) or ""

        errors = {}

        if not self.invoice_number:
            errors["invoice_number"] = "Invoice number cannot be blank."

        if self.student_id and self.student.school_id != self.school_id:
            errors["student"] = "The student must belong to the same school."

        if self.academic_term_id and self.academic_term.school_id != self.school_id:
            errors["academic_term"] = "The academic term must belong to the same school."

        if self.created_by_id and not self.created_by.is_superuser:
            if self.created_by.school_id != self.school_id:
                errors["created_by"] = "The creator must belong to the same school."

        if self.issue_date and self.due_date and self.issue_date > self.due_date:
            errors["due_date"] = "Due date cannot be before the issue date."

        if self.discount_amount is not None and self.subtotal is not None:
            allowed_discount_ceiling = self.subtotal + max(self.adjustment_amount or ZERO, ZERO)
            if self.discount_amount > allowed_discount_ceiling:
                errors["discount_amount"] = (
                    "Discount amount must not exceed the subtotal plus any "
                    "positive adjustment."
                )

        if self.amount_paid is not None and self.total_amount is not None:
            if self.amount_paid > self.total_amount:
                errors["amount_paid"] = (
                    "Amount paid must not exceed the total amount unless "
                    "overpayment support is explicitly enabled."
                )

        if self.status == self.Status.CANCELLED and self.amount_paid and self.amount_paid > ZERO:
            errors["status"] = "A cancelled invoice cannot have a positive amount paid."

        if self.status == self.Status.PAID and self.balance and self.balance != ZERO:
            errors["balance"] = "A paid invoice must have a zero balance."

        if self.status == self.Status.PARTIALLY_PAID:
            if not (self.amount_paid and self.amount_paid > ZERO):
                errors["amount_paid"] = (
                    "A partially paid invoice must have an amount paid "
                    "greater than zero."
                )
            if not (self.balance and self.balance > ZERO):
                errors["balance"] = (
                    "A partially paid invoice must have a balance greater "
                    "than zero."
                )

        if self.status == self.Status.DRAFT and self.amount_paid and self.amount_paid > ZERO:
            errors["status"] = "A draft invoice should not have any allocated payments."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def computed_item_subtotal(self):
        """Live sum of item totals — for comparison/reporting, not storage."""
        return self.items.aggregate(total=models.Sum("total_amount"))["total"] or ZERO

    @property
    def computed_completed_allocation_total(self):
        """Live sum of allocations from completed payments — not storage."""
        return self.allocations.filter(
            payment__status=Payment.Status.COMPLETED,
        ).aggregate(total=models.Sum("amount"))["total"] or ZERO


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(
        StudentInvoice,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Invoice",
    )
    fee_structure = models.ForeignKey(
        FeeStructure,
        on_delete=models.PROTECT,
        related_name="invoice_items",
        null=True,
        blank=True,
        verbose_name="Fee Structure",
    )
    fee_category = models.ForeignKey(
        FeeCategory,
        on_delete=models.PROTECT,
        related_name="invoice_items",
        verbose_name="Fee Category",
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="Description")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Quantity")
    unit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(MIN_POSITIVE)],
        verbose_name="Unit Amount",
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Discount Amount",
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Total Amount",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Invoice Item"
        verbose_name_plural = "Invoice Items"
        ordering = ["invoice", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="invoice_item_quantity_at_least_one",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_amount__gt=ZERO),
                name="invoice_item_unit_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=ZERO),
                name="invoice_item_discount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=ZERO),
                name="invoice_item_total_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["invoice"]),
        ]

    def __str__(self):
        return f"{self.description or self.fee_category} - {self.invoice}"

    def clean(self):
        self.description = _norm(self.description) or ""
        errors = {}

        if self.quantity is not None and self.quantity < 1:
            errors["quantity"] = "Quantity must be at least 1."

        if self.unit_amount is not None and self.unit_amount <= ZERO:
            errors["unit_amount"] = "Unit amount must be greater than zero."

        if self.discount_amount is not None and self.discount_amount < ZERO:
            errors["discount_amount"] = "Discount amount must not be negative."

        if (
            self.unit_amount is not None
            and self.quantity is not None
            and self.discount_amount is not None
        ):
            gross = self.unit_amount * self.quantity
            if self.discount_amount > gross:
                errors["discount_amount"] = (
                    "Discount amount must not exceed the item's gross amount "
                    "(unit amount x quantity)."
                )

        if self.invoice_id and self.invoice.status in (
            StudentInvoice.Status.PAID,
            StudentInvoice.Status.CANCELLED,
        ):
            errors["invoice"] = (
                "Items cannot be added or changed on a paid or cancelled "
                "invoice."
            )

        if self.fee_structure_id and self.invoice_id:
            fee_structure = self.fee_structure
            invoice = self.invoice

            if fee_structure.school_id != invoice.school_id:
                errors["fee_structure"] = (
                    "The fee structure must belong to the same school as "
                    "the invoice."
                )

            if fee_structure.academic_term_id != invoice.academic_term_id:
                errors["fee_structure"] = (
                    "The fee structure must belong to the same academic "
                    "term as the invoice."
                )

            student_classroom_id = getattr(invoice.student, "classroom_id", None)
            if (
                fee_structure.classroom_id is not None
                and fee_structure.classroom_id != student_classroom_id
            ):
                errors["fee_structure"] = (
                    "The fee structure must either be school-wide or match "
                    "the invoice student's classroom."
                )

            if (
                self.fee_category_id
                and self.fee_category_id != fee_structure.fee_category_id
            ):
                errors["fee_category"] = (
                    "The fee category must match the fee structure's fee "
                    "category."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Only this item's own total is calculated here. Recalculating the
        # parent invoice's subtotal/total belongs to finance/services.py.
        quantity = self.quantity or 0
        unit_amount = self.unit_amount or ZERO
        discount_amount = self.discount_amount or ZERO
        self.total_amount = (unit_amount * quantity) - discount_amount
        self.full_clean()
        super().save(*args, **kwargs)


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        REVERSED = "reversed", "Reversed"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="School",
    )
    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Student",
    )
    payment_reference = models.CharField(
        max_length=60, verbose_name="Payment Reference"
    )
    payment_date = models.DateField(verbose_name="Payment Date")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(MIN_POSITIVE)],
        verbose_name="Amount",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        verbose_name="Payment Method",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Status",
    )
    external_reference = models.CharField(
        max_length=100, blank=True, verbose_name="External Reference"
    )
    payment_proof = models.FileField(
        upload_to=payment_proof_upload_path,
        null=True,
        blank=True,
        verbose_name="Payment Proof",
        help_text="File type and size validation is handled at the serializer level.",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    received_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="received_payments",
        verbose_name="Received By",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ["-payment_date", "school"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "payment_reference"],
                name="unique_payment_reference_per_school",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=ZERO),
                name="payment_amount_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "student", "status"]),
            models.Index(fields=["school", "payment_date"]),
            models.Index(fields=["external_reference"]),
        ]

    def __str__(self):
        return f"{self.payment_reference} - {self.student} ({self.school})"

    def clean(self):
        self.payment_reference = _norm(self.payment_reference)
        self.external_reference = _norm(self.external_reference) or ""
        self.notes = _norm(self.notes) or ""

        errors = {}

        if not self.payment_reference:
            errors["payment_reference"] = "Payment reference cannot be blank."

        if self.student_id and self.school_id and self.student.school_id != self.school_id:
            errors["student"] = "The student must belong to the same school."

        if self.amount is not None and self.amount <= ZERO:
            errors["amount"] = "Amount must be greater than zero."

        if self.received_by_id and not self.received_by.is_superuser:
            if self.received_by.school_id != self.school_id:
                errors["received_by"] = "The receiver must belong to the same school."

        if self.pk:
            previous_status = (
                Payment.objects.filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
            if (
                previous_status == self.Status.COMPLETED
                and self.status == self.Status.PENDING
            ):
                errors["status"] = (
                    "A completed payment cannot be reverted to pending "
                    "through an ordinary save; use the service-layer "
                    "reversal/cancellation workflow instead."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def allocated_amount(self):
        """Live sum of this payment's allocations — not a stored value."""
        return self.allocations.aggregate(total=models.Sum("amount"))["total"] or ZERO

    @property
    def unallocated_amount(self):
        """Live computed remainder — not a stored value."""
        return self.amount - self.allocated_amount

    @property
    def is_active_money(self):
        """Whether this payment currently represents usable funds."""
        return self.status == self.Status.COMPLETED


class PaymentAllocation(models.Model):
    """
    Links a completed payment to an invoice for a specific amount.

    Race-sensitive limits (unallocated payment balance, outstanding invoice
    balance) are NOT fully enforced here because clean() cannot safely lock
    rows. finance/services.py must wrap allocation creation in
    transaction.atomic() with select_for_update() on both the Payment and
    StudentInvoice rows before validating and saving an allocation.

    Multiple allocation rows for the same (payment, invoice) pair are
    intentionally allowed — a single payment may be topped up against the
    same invoice on separate occasions, and collapsing them into one row
    would lose that history.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="allocations",
        verbose_name="Payment",
    )
    invoice = models.ForeignKey(
        StudentInvoice,
        on_delete=models.PROTECT,
        related_name="allocations",
        verbose_name="Invoice",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(MIN_POSITIVE)],
        verbose_name="Amount",
    )
    allocated_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="payment_allocations",
        verbose_name="Allocated By",
    )
    allocated_at = models.DateTimeField(auto_now_add=True, verbose_name="Allocated At")

    class Meta:
        verbose_name = "Payment Allocation"
        verbose_name_plural = "Payment Allocations"
        ordering = ["-allocated_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=ZERO),
                name="payment_allocation_amount_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["payment"]),
            models.Index(fields=["invoice"]),
        ]

    def __str__(self):
        return f"{self.payment} -> {self.invoice}: {self.amount}"

    def clean(self):
        errors = {}

        if self.payment_id and self.invoice_id:
            if self.payment.school_id != self.invoice.school_id:
                errors["invoice"] = "The payment and invoice must belong to the same school."
            if self.payment.student_id != self.invoice.student_id:
                errors["invoice"] = "The payment and invoice must belong to the same student."

        if self.payment_id and self.payment.status != Payment.Status.COMPLETED:
            errors["payment"] = "Only completed payments can be allocated."

        if self.invoice_id and self.invoice.status in (
            StudentInvoice.Status.DRAFT,
            StudentInvoice.Status.CANCELLED,
        ):
            errors["invoice"] = "Draft or cancelled invoices cannot receive allocations."

        if self.amount is not None and self.amount <= ZERO:
            errors["amount"] = "Allocation amount must be greater than zero."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Receipt(models.Model):
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="receipts",
        verbose_name="School",
    )
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="receipt",
        verbose_name="Payment",
    )
    receipt_number = models.CharField(max_length=50, verbose_name="Receipt Number")
    issued_at = models.DateTimeField(auto_now_add=True, verbose_name="Issued At")
    issued_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="issued_receipts",
        verbose_name="Issued By",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "receipt_number"],
                name="unique_receipt_number_per_school",
            ),
        ]
        indexes = [
            models.Index(fields=["school"]),
        ]

    def __str__(self):
        return f"{self.receipt_number} ({self.school})"

    def clean(self):
        self.receipt_number = _norm(self.receipt_number)
        self.notes = _norm(self.notes) or ""

        errors = {}

        if not self.receipt_number:
            errors["receipt_number"] = "Receipt number cannot be blank."

        if self.payment_id and self.payment.school_id != self.school_id:
            errors["payment"] = "The payment must belong to the same school."

        if self.payment_id and self.payment.status != Payment.Status.COMPLETED:
            errors["payment"] = "A receipt can only be issued for a completed payment."

        if self.issued_by_id and not self.issued_by.is_superuser:
            if self.issued_by.school_id != self.school_id:
                errors["issued_by"] = "The issuer must belong to the same school."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Expense(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name="School",
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name="expenses",
        null=True,
        blank=True,
        verbose_name="Category",
    )
    description = models.CharField(max_length=255, verbose_name="Description")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(MIN_POSITIVE)],
        verbose_name="Amount",
    )
    expense_date = models.DateField(verbose_name="Expense Date")
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        verbose_name="Payment Method",
    )
    reference = models.CharField(max_length=100, blank=True, verbose_name="Reference")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Status",
    )
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="recorded_expenses",
        verbose_name="Recorded By",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_expenses",
        verbose_name="Approved By",
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="Approved At")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"
        ordering = ["-expense_date", "school"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=ZERO),
                name="expense_amount_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "status"]),
        ]

    def __str__(self):
        return f"{self.description} ({self.school})"

    def clean(self):
        self.description = _norm(self.description)
        self.reference = _norm(self.reference) or ""

        errors = {}

        if not self.description:
            errors["description"] = "Description cannot be blank."

        if self.category_id and self.category.school_id != self.school_id:
            errors["category"] = "The category must belong to the same school."

        if self.amount is not None and self.amount <= ZERO:
            errors["amount"] = "Amount must be greater than zero."

        if self.recorded_by_id and not self.recorded_by.is_superuser:
            if self.recorded_by.school_id != self.school_id:
                errors["recorded_by"] = "The recorder must belong to the same school."

        if self.approved_by_id and not self.approved_by.is_superuser:
            if self.approved_by.school_id != self.school_id:
                errors["approved_by"] = "The approver must belong to the same school."

        if bool(self.approved_by_id) != bool(self.approved_at):
            errors["approved_at"] = (
                "Approved_by and approved_at must be set or unset together."
            )

        if self.status in (self.Status.DRAFT, self.Status.SUBMITTED):
            if self.approved_by_id or self.approved_at:
                errors["status"] = (
                    "Draft or submitted expenses should not have approval "
                    "metadata."
                )

        if self.status in (self.Status.APPROVED, self.Status.PAID):
            if not self.approved_by_id or not self.approved_at:
                errors["status"] = (
                    "Approved or paid expenses must have approval metadata."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class FinancialTransaction(models.Model):
    """
    Immutable, append-only audit trail of important financial actions.

    This model must never be updated or deleted through normal API
    operations; only created by finance/services.py as a side effect of a
    controlled financial action.
    """

    class TransactionType(models.TextChoices):
        INVOICE_ISSUED = "invoice_issued", "Invoice Issued"
        INVOICE_CANCELLED = "invoice_cancelled", "Invoice Cancelled"
        PAYMENT_RECORDED = "payment_recorded", "Payment Recorded"
        PAYMENT_ALLOCATED = "payment_allocated", "Payment Allocated"
        PAYMENT_REVERSED = "payment_reversed", "Payment Reversed"
        PAYMENT_CANCELLED = "payment_cancelled", "Payment Cancelled"
        EXPENSE_RECORDED = "expense_recorded", "Expense Recorded"
        EXPENSE_APPROVED = "expense_approved", "Expense Approved"

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="financial_transactions",
        verbose_name="School",
    )
    transaction_type = models.CharField(
        max_length=30,
        choices=TransactionType.choices,
        verbose_name="Transaction Type",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Amount",
        help_text="May be zero only for event types with no financial amount.",
    )
    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_transactions",
        verbose_name="Student",
    )
    invoice = models.ForeignKey(
        StudentInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="Invoice",
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="Payment",
    )
    expense = models.ForeignKey(
        Expense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="Expense",
    )
    reference = models.CharField(max_length=100, blank=True, verbose_name="Reference")
    description = models.CharField(max_length=255, blank=True, verbose_name="Description")
    metadata = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Metadata",
        help_text="Optional immutable snapshot data captured at creation time.",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_financial_transactions",
        verbose_name="Created By",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Financial Transaction"
        verbose_name_plural = "Financial Transactions"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["school", "transaction_type"]),
            models.Index(fields=["school", "created_at"]),
            models.Index(fields=["student", "created_at"]),
            models.Index(fields=["reference"]),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} ({self.school})"

    def clean(self):
        self.reference = _norm(self.reference) or ""
        self.description = _norm(self.description) or ""

        errors = {}

        for field_name, obj in (
            ("student", self.student),
            ("invoice", self.invoice),
            ("payment", self.payment),
            ("expense", self.expense),
        ):
            if obj is not None and getattr(obj, "school_id", None) != self.school_id:
                errors[field_name] = "This reference must belong to the same school."

        if self.created_by_id and not self.created_by.is_superuser:
            if self.created_by.school_id != self.school_id:
                errors["created_by"] = "The creator must belong to the same school."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Intentionally does not special-case updates: this model is only
        # ever created (never updated) by finance/services.py, so
        # full_clean() on every save remains safe and cheap.
        self.full_clean()
        super().save(*args, **kwargs)