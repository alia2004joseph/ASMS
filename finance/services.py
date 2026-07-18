# finance/services.py

from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError as DjangoValidationError

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Expense,
    FinancialTransaction,
    Payment,
    PaymentAllocation,
    Receipt,
    StudentInvoice,
)

ZERO = Decimal("0.00")


class FinanceServiceError(Exception):
    """Raised when a finance business rule is violated."""


def _to_decimal(value, field_name="amount"):
    """Convert a supplied value to Decimal and raise a service-friendly error."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FinanceServiceError(
            f"{field_name.replace('_', ' ').title()} must be a valid number."
        ) from exc

    return amount.quantize(Decimal("0.01"))


def _normalize_text(value):
    """Return trimmed text without converting blank values to None."""
    return (value or "").strip()


def _validate_actor_school(user, school_id):
    """Ensure a non-superuser actor belongs to the affected school."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise FinanceServiceError("An authenticated user is required.")

    if getattr(user, "is_superuser", False):
        return

    if getattr(user, "school_id", None) != school_id:
        raise FinanceServiceError(
            "You cannot perform this finance action for another school."
        )


def _create_transaction(
    *,
    school,
    transaction_type,
    amount,
    created_by,
    student=None,
    invoice=None,
    payment=None,
    expense=None,
    reference="",
    description="",
    metadata=None,
):
    """Create one immutable financial audit entry."""
    return FinancialTransaction.objects.create(
        school=school,
        transaction_type=transaction_type,
        amount=_to_decimal(amount),
        student=student,
        invoice=invoice,
        payment=payment,
        expense=expense,
        reference=_normalize_text(reference),
        description=_normalize_text(description),
        metadata=metadata or None,
        created_by=created_by,
    )


def recalculate_invoice_totals(invoice, save=True):
    """Recalculate invoice subtotal and total from its items."""
    subtotal = invoice.items.aggregate(total=Sum("total_amount"))["total"] or ZERO
    discount = invoice.discount_amount or ZERO
    adjustment = invoice.adjustment_amount or ZERO

    total = subtotal - discount + adjustment
    if total < ZERO:
        raise FinanceServiceError(
            "Invoice total cannot be negative. Review its discount and adjustment amounts."
        )

    invoice.subtotal = subtotal
    invoice.total_amount = total

    if save:
        invoice.save(update_fields=["subtotal", "total_amount", "updated_at"])

    return invoice


def recalculate_invoice_payment_state(invoice, save=True):
    """Recalculate amount paid, balance and status from completed allocations."""
    allocated = (
        invoice.allocations.filter(payment__status=Payment.Status.COMPLETED)
        .aggregate(total=Sum("amount"))["total"]
        or ZERO
    )

    if allocated > invoice.total_amount:
        raise FinanceServiceError(
            "Completed payment allocations exceed the invoice total."
        )

    invoice.amount_paid = allocated
    invoice.balance = invoice.total_amount - allocated

    if invoice.status not in (
        StudentInvoice.Status.DRAFT,
        StudentInvoice.Status.CANCELLED,
    ):
        if invoice.balance == ZERO:
            invoice.status = StudentInvoice.Status.PAID
        elif invoice.amount_paid > ZERO:
            invoice.status = StudentInvoice.Status.PARTIALLY_PAID
        elif invoice.due_date and invoice.due_date < timezone.localdate():
            invoice.status = StudentInvoice.Status.OVERDUE
        else:
            invoice.status = StudentInvoice.Status.ISSUED

    if save:
        invoice.save(
            update_fields=["amount_paid", "balance", "status", "updated_at"]
        )

    return invoice


@transaction.atomic
def issue_invoice(invoice, user):
    """Issue a draft invoice after recalculating its stored totals."""
    locked_invoice = (
        StudentInvoice.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=invoice.pk)
    )
    _validate_actor_school(user, locked_invoice.school_id)

    if locked_invoice.status != StudentInvoice.Status.DRAFT:
        raise FinanceServiceError("Only draft invoices can be issued.")

    if not locked_invoice.items.exists():
        raise FinanceServiceError("Cannot issue an invoice with no items.")

    recalculate_invoice_totals(locked_invoice, save=False)
    locked_invoice.amount_paid = ZERO
    locked_invoice.balance = locked_invoice.total_amount
    locked_invoice.status = StudentInvoice.Status.ISSUED
    locked_invoice.save(
        update_fields=[
            "subtotal",
            "total_amount",
            "amount_paid",
            "balance",
            "status",
            "updated_at",
        ]
    )

    _create_transaction(
        school=locked_invoice.school,
        transaction_type=FinancialTransaction.TransactionType.INVOICE_ISSUED,
        amount=locked_invoice.total_amount,
        student=locked_invoice.student,
        invoice=locked_invoice,
        reference=locked_invoice.invoice_number,
        description=f"Invoice {locked_invoice.invoice_number} issued.",
        metadata={
            "invoice_number": locked_invoice.invoice_number,
            "academic_term_id": locked_invoice.academic_term_id,
        },
        created_by=user,
    )

    return locked_invoice


@transaction.atomic
def cancel_invoice(invoice, user, reason=""):
    """Cancel an unpaid invoice and record the action in the audit trail."""
    locked_invoice = (
        StudentInvoice.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=invoice.pk)
    )
    _validate_actor_school(user, locked_invoice.school_id)

    if locked_invoice.status == StudentInvoice.Status.PAID:
        raise FinanceServiceError("Paid invoices cannot be cancelled.")

    if locked_invoice.status == StudentInvoice.Status.CANCELLED:
        raise FinanceServiceError("This invoice is already cancelled.")

    completed_allocations = locked_invoice.allocations.filter(
        payment__status=Payment.Status.COMPLETED
    ).exists()
    if locked_invoice.amount_paid > ZERO or completed_allocations:
        raise FinanceServiceError(
            "Invoices with completed payment allocations cannot be cancelled directly. "
            "Reverse the related payments first."
        )

    reason = _normalize_text(reason)
    locked_invoice.status = StudentInvoice.Status.CANCELLED
    locked_invoice.save(update_fields=["status", "updated_at"])

    _create_transaction(
        school=locked_invoice.school,
        transaction_type=FinancialTransaction.TransactionType.INVOICE_CANCELLED,
        amount=locked_invoice.total_amount,
        student=locked_invoice.student,
        invoice=locked_invoice,
        reference=locked_invoice.invoice_number,
        description=reason or f"Invoice {locked_invoice.invoice_number} cancelled.",
        metadata={"reason": reason},
        created_by=user,
    )

    return locked_invoice


@transaction.atomic
def record_payment(payment, user):
    """Mark a pending payment as completed and log it."""
    locked_payment = (
        Payment.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=payment.pk)
    )
    _validate_actor_school(user, locked_payment.school_id)

    if locked_payment.status != Payment.Status.PENDING:
        raise FinanceServiceError("Only pending payments can be completed.")

    if locked_payment.amount <= ZERO:
        raise FinanceServiceError("Payment amount must be greater than zero.")

    locked_payment.status = Payment.Status.COMPLETED
    if not locked_payment.received_by_id:
        locked_payment.received_by = user

    locked_payment.save(update_fields=["status", "received_by", "updated_at"])

    _create_transaction(
        school=locked_payment.school,
        transaction_type=FinancialTransaction.TransactionType.PAYMENT_RECORDED,
        amount=locked_payment.amount,
        student=locked_payment.student,
        payment=locked_payment,
        reference=locked_payment.payment_reference,
        description=f"Payment {locked_payment.payment_reference} recorded.",
        metadata={
            "payment_method": locked_payment.payment_method,
            "external_reference": locked_payment.external_reference,
        },
        created_by=user,
    )

    return locked_payment


@transaction.atomic
def allocate_payment(payment, invoice, amount, user):
    """Allocate completed payment funds to an unpaid invoice safely."""
    amount = _to_decimal(amount, "allocation amount")

    locked_payment = (
        Payment.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=payment.pk)
    )
    locked_invoice = (
        StudentInvoice.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=invoice.pk)
    )
    _validate_actor_school(user, locked_payment.school_id)

    if locked_payment.status != Payment.Status.COMPLETED:
        raise FinanceServiceError("Only completed payments can be allocated.")

    if locked_payment.school_id != locked_invoice.school_id:
        raise FinanceServiceError(
            "The payment and invoice must belong to the same school."
        )

    if locked_payment.student_id != locked_invoice.student_id:
        raise FinanceServiceError(
            "The payment and invoice must belong to the same student."
        )

    if locked_invoice.status in (
        StudentInvoice.Status.DRAFT,
        StudentInvoice.Status.CANCELLED,
        StudentInvoice.Status.PAID,
    ):
        raise FinanceServiceError(
            "Payments can only be allocated to an unpaid issued or overdue invoice."
        )

    if amount <= ZERO:
        raise FinanceServiceError("Allocation amount must be greater than zero.")

    allocated_payment_total = (
        locked_payment.allocations.aggregate(total=Sum("amount"))["total"] or ZERO
    )
    unallocated = locked_payment.amount - allocated_payment_total

    completed_invoice_total = (
        locked_invoice.allocations.filter(payment__status=Payment.Status.COMPLETED)
        .aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    outstanding = locked_invoice.total_amount - completed_invoice_total

    if amount > unallocated:
        raise FinanceServiceError(
            "Allocation amount exceeds the payment's unallocated balance."
        )

    if amount > outstanding:
        raise FinanceServiceError(
            "Allocation amount exceeds the invoice's outstanding balance."
        )

    try:
        allocation = PaymentAllocation.objects.create(
            payment=locked_payment,
            invoice=locked_invoice,
            amount=amount,
            allocated_by=user,
        )
    except IntegrityError as exc:
        raise FinanceServiceError(
            "The payment allocation could not be created."
        ) from exc

    recalculate_invoice_payment_state(locked_invoice)

    _create_transaction(
        school=locked_invoice.school,
        transaction_type=FinancialTransaction.TransactionType.PAYMENT_ALLOCATED,
        amount=amount,
        student=locked_invoice.student,
        invoice=locked_invoice,
        payment=locked_payment,
        reference=locked_payment.payment_reference,
        description=(
            f"Payment {locked_payment.payment_reference} allocated to "
            f"invoice {locked_invoice.invoice_number}."
        ),
        metadata={
            "allocation_id": allocation.pk,
            "invoice_number": locked_invoice.invoice_number,
        },
        created_by=user,
    )

    return allocation


@transaction.atomic
def reverse_payment(payment, user, reason=""):
    """Reverse a completed payment and recalculate every affected invoice."""
    locked_payment = (
        Payment.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=payment.pk)
    )
    _validate_actor_school(user, locked_payment.school_id)

    if locked_payment.status != Payment.Status.COMPLETED:
        raise FinanceServiceError("Only completed payments can be reversed.")

    affected_invoice_ids = list(
        locked_payment.allocations.values_list("invoice_id", flat=True).distinct()
    )

    locked_payment.status = Payment.Status.REVERSED
    locked_payment.save(update_fields=["status", "updated_at"])

    for invoice_id in affected_invoice_ids:
        affected_invoice = StudentInvoice.objects.select_for_update().get(pk=invoice_id)
        recalculate_invoice_payment_state(affected_invoice)

    reason = _normalize_text(reason)
    _create_transaction(
        school=locked_payment.school,
        transaction_type=FinancialTransaction.TransactionType.PAYMENT_REVERSED,
        amount=locked_payment.amount,
        student=locked_payment.student,
        payment=locked_payment,
        reference=locked_payment.payment_reference,
        description=reason or f"Payment {locked_payment.payment_reference} reversed.",
        metadata={
            "reason": reason,
            "affected_invoice_ids": affected_invoice_ids,
        },
        created_by=user,
    )

    return locked_payment


@transaction.atomic
def cancel_payment(payment, user, reason=""):
    """Cancel a pending, unallocated payment."""
    locked_payment = (
        Payment.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=payment.pk)
    )
    _validate_actor_school(user, locked_payment.school_id)

    if locked_payment.status != Payment.Status.PENDING:
        raise FinanceServiceError(
            "Only pending payments can be cancelled. Completed payments must be reversed."
        )

    if locked_payment.allocations.exists():
        raise FinanceServiceError("An allocated payment cannot be cancelled.")

    reason = _normalize_text(reason)
    locked_payment.status = Payment.Status.CANCELLED
    locked_payment.save(update_fields=["status", "updated_at"])

    _create_transaction(
        school=locked_payment.school,
        transaction_type=FinancialTransaction.TransactionType.PAYMENT_CANCELLED,
        amount=locked_payment.amount,
        student=locked_payment.student,
        payment=locked_payment,
        reference=locked_payment.payment_reference,
        description=reason or f"Payment {locked_payment.payment_reference} cancelled.",
        metadata={"reason": reason},
        created_by=user,
    )

    return locked_payment


@transaction.atomic
def generate_receipt(payment, user, receipt_number):
    """Create one receipt for a completed payment."""
    locked_payment = (
        Payment.objects.select_for_update()
        .select_related("school", "student")
        .get(pk=payment.pk)
    )
    _validate_actor_school(user, locked_payment.school_id)

    if locked_payment.status != Payment.Status.COMPLETED:
        raise FinanceServiceError(
            "Only completed payments can have a receipt issued."
        )

    receipt_number = _normalize_text(receipt_number)
    if not receipt_number:
        raise FinanceServiceError("Receipt number cannot be blank.")

    if Receipt.objects.filter(payment=locked_payment).exists():
        raise FinanceServiceError(
            "A receipt has already been issued for this payment."
        )

    try:
        return Receipt.objects.create(
            school=locked_payment.school,
            payment=locked_payment,
            receipt_number=receipt_number,
            issued_by=user,
        )

    except DjangoValidationError as exc:
        messages = exc.message_dict.get("__all__", [])

        if any(
            "Receipt with this School and Receipt Number already exists"
            in message
            for message in messages
        ):
            raise FinanceServiceError(
                "This receipt number is already in use for this school."
            ) from exc

        raise FinanceServiceError(
            "The receipt could not be created."
        ) from exc

    except IntegrityError as exc:
        raise FinanceServiceError(
            "This receipt number is already in use for this school."
        ) from exc

@transaction.atomic
def submit_expense(expense, user):
    """Move a draft expense into the approval queue."""
    locked_expense = (
        Expense.objects.select_for_update()
        .select_related("school")
        .get(pk=expense.pk)
    )
    _validate_actor_school(user, locked_expense.school_id)

    if locked_expense.status != Expense.Status.DRAFT:
        raise FinanceServiceError("Only draft expenses can be submitted.")

    locked_expense.status = Expense.Status.SUBMITTED
    locked_expense.save(update_fields=["status", "updated_at"])
    return locked_expense


@transaction.atomic
def approve_expense(expense, user):
    """Approve a submitted expense and create an audit entry."""
    locked_expense = (
        Expense.objects.select_for_update()
        .select_related("school")
        .get(pk=expense.pk)
    )
    _validate_actor_school(user, locked_expense.school_id)

    if locked_expense.status != Expense.Status.SUBMITTED:
        raise FinanceServiceError("Only submitted expenses can be approved.")

    locked_expense.status = Expense.Status.APPROVED
    locked_expense.approved_by = user
    locked_expense.approved_at = timezone.now()
    locked_expense.save(
        update_fields=["status", "approved_by", "approved_at", "updated_at"]
    )

    _create_transaction(
        school=locked_expense.school,
        transaction_type=FinancialTransaction.TransactionType.EXPENSE_APPROVED,
        amount=locked_expense.amount,
        expense=locked_expense,
        reference=locked_expense.reference,
        description=f"Expense '{locked_expense.description}' approved.",
        metadata={"approved_at": locked_expense.approved_at.isoformat()},
        created_by=user,
    )

    return locked_expense


@transaction.atomic
def reject_expense(expense, user, reason=""):
    """Reject a submitted expense."""
    locked_expense = (
        Expense.objects.select_for_update()
        .select_related("school")
        .get(pk=expense.pk)
    )
    _validate_actor_school(user, locked_expense.school_id)

    if locked_expense.status != Expense.Status.SUBMITTED:
        raise FinanceServiceError("Only submitted expenses can be rejected.")

    locked_expense.status = Expense.Status.REJECTED
    locked_expense.approved_by = None
    locked_expense.approved_at = None
    locked_expense.save(
        update_fields=["status", "approved_by", "approved_at", "updated_at"]
    )

    # Add EXPENSE_REJECTED to FinancialTransaction.TransactionType later if
    # rejected-expense audit events must have a dedicated transaction type.
    return locked_expense


@transaction.atomic
def mark_expense_paid(expense, user):
    """Mark an approved expense as paid."""
    locked_expense = (
        Expense.objects.select_for_update()
        .select_related("school")
        .get(pk=expense.pk)
    )
    _validate_actor_school(user, locked_expense.school_id)

    if locked_expense.status != Expense.Status.APPROVED:
        raise FinanceServiceError("Only approved expenses can be marked as paid.")

    locked_expense.status = Expense.Status.PAID
    locked_expense.save(update_fields=["status", "updated_at"])

    _create_transaction(
        school=locked_expense.school,
        transaction_type=FinancialTransaction.TransactionType.EXPENSE_RECORDED,
        amount=locked_expense.amount,
        expense=locked_expense,
        reference=locked_expense.reference,
        description=f"Expense '{locked_expense.description}' marked as paid.",
        metadata={"event": "expense_paid"},
        created_by=user,
    )

    return locked_expense


@transaction.atomic
def cancel_expense(expense, user, reason=""):
    """Cancel an expense that has not been paid."""
    locked_expense = (
        Expense.objects.select_for_update()
        .select_related("school")
        .get(pk=expense.pk)
    )
    _validate_actor_school(user, locked_expense.school_id)

    if locked_expense.status == Expense.Status.PAID:
        raise FinanceServiceError("Paid expenses cannot be cancelled.")

    if locked_expense.status == Expense.Status.CANCELLED:
        raise FinanceServiceError("This expense is already cancelled.")

    locked_expense.status = Expense.Status.CANCELLED
    locked_expense.save(update_fields=["status", "updated_at"])

    # Add EXPENSE_CANCELLED to FinancialTransaction.TransactionType later if
    # cancelled-expense audit events require a dedicated transaction type.
    return locked_expense