from decimal import Decimal

from django.test import TestCase

from finance.models import (
    FinancialTransaction,
    Payment,
    StudentInvoice,
)
from finance.services import (
    FinanceServiceError,
    allocate_payment,
    cancel_payment,
    issue_invoice,
    record_payment,
    reverse_payment,
)

from .factories import (
    create_accountant,
    create_academic_term,
    create_academic_year,
    create_classroom,
    create_fee_category,
    create_fee_structure,
    create_invoice,
    create_invoice_item,
    create_payment,
    create_school,
    create_student,
)


class PaymentServiceTests(TestCase):
    def setUp(self):
        self.school = create_school()
        self.accountant = create_accountant(self.school)

        self.academic_year = create_academic_year(self.school)
        self.academic_term = create_academic_term(
            self.school,
            self.academic_year,
        )
        self.classroom = create_classroom(
            self.school,
            self.academic_year,
        )
        self.student = create_student(
            self.school,
            classroom=self.classroom,
        )

        self.fee_category = create_fee_category(self.school)
        self.fee_structure = create_fee_structure(
            self.school,
            self.academic_term,
            self.classroom,
            self.fee_category,
            self.accountant,
        )

        self.invoice = create_invoice(
            self.school,
            self.student,
            self.academic_term,
            self.accountant,
        )
        create_invoice_item(
            self.invoice,
            self.fee_structure,
        )
        self.invoice = issue_invoice(
            self.invoice,
            self.accountant,
        )

        self.payment = create_payment(
            self.school,
            self.student,
            self.accountant,
        )

    def test_record_payment_marks_payment_completed(self):
        payment = record_payment(
            self.payment,
            self.accountant,
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            Payment.Status.COMPLETED,
        )
        self.assertEqual(
            payment.received_by,
            self.accountant,
        )

    def test_record_payment_creates_transaction(self):
        payment = record_payment(
            self.payment,
            self.accountant,
        )

        transaction = FinancialTransaction.objects.get(
            payment=payment,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_RECORDED
            ),
        )

        self.assertEqual(transaction.school, self.school)
        self.assertEqual(transaction.student, self.student)
        self.assertEqual(transaction.amount, Decimal("100000.00"))
        self.assertEqual(transaction.created_by, self.accountant)
        self.assertEqual(
            transaction.reference,
            payment.payment_reference,
        )

    def test_cannot_record_completed_payment_again(self):
        record_payment(
            self.payment,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only pending payments can be completed.",
        ):
            record_payment(
                self.payment,
                self.accountant,
            )

        transactions = FinancialTransaction.objects.filter(
            payment=self.payment,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_RECORDED
            ),
        )

        self.assertEqual(transactions.count(), 1)

    def test_other_school_user_cannot_record_payment(self):
        other_school = create_school(
            name="Other School",
            code="OTHER",
        )
        other_accountant = create_accountant(
            other_school,
            email="other-payment-accountant@test.com",
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "You cannot perform this finance action for another school.",
        ):
            record_payment(
                self.payment,
                other_accountant,
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.PENDING,
        )

    def test_allocate_payment_updates_invoice_to_paid(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        allocation = allocate_payment(
            completed_payment,
            self.invoice,
            Decimal("100000.00"),
            self.accountant,
        )

        self.invoice.refresh_from_db()

        self.assertEqual(
            allocation.amount,
            Decimal("100000.00"),
        )
        self.assertEqual(
            self.invoice.amount_paid,
            Decimal("100000.00"),
        )
        self.assertEqual(
            self.invoice.balance,
            Decimal("0.00"),
        )
        self.assertEqual(
            self.invoice.status,
            StudentInvoice.Status.PAID,
        )

    def test_partial_allocation_updates_invoice_status(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        allocate_payment(
            completed_payment,
            self.invoice,
            Decimal("40000.00"),
            self.accountant,
        )

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.amount_paid,
            Decimal("40000.00"),
        )
        self.assertEqual(
            self.invoice.balance,
            Decimal("60000.00"),
        )
        self.assertEqual(
            self.invoice.status,
            StudentInvoice.Status.PARTIALLY_PAID,
        )

    def test_allocate_payment_creates_transaction(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        allocation = allocate_payment(
            completed_payment,
            self.invoice,
            Decimal("30000.00"),
            self.accountant,
        )

        transaction = FinancialTransaction.objects.get(
            payment=completed_payment,
            invoice=self.invoice,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_ALLOCATED
            ),
        )

        self.assertEqual(
            transaction.amount,
            Decimal("30000.00"),
        )
        self.assertEqual(
            transaction.metadata["allocation_id"],
            allocation.pk,
        )

    def test_cannot_allocate_pending_payment(self):
        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only completed payments can be allocated.",
        ):
            allocate_payment(
                self.payment,
                self.invoice,
                Decimal("10000.00"),
                self.accountant,
            )

    def test_cannot_allocate_more_than_payment_balance(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Allocation amount exceeds the payment's unallocated balance.",
        ):
            allocate_payment(
                completed_payment,
                self.invoice,
                Decimal("120000.00"),
                self.accountant,
            )

    def test_cannot_allocate_more_than_invoice_balance(self):
        self.payment.amount = Decimal("150000.00")
        self.payment.save(update_fields=["amount", "updated_at"])

        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Allocation amount exceeds the invoice's outstanding balance.",
        ):
            allocate_payment(
                completed_payment,
                self.invoice,
                Decimal("110000.00"),
                self.accountant,
            )

    def test_cannot_allocate_zero_amount(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Allocation amount must be greater than zero.",
        ):
            allocate_payment(
                completed_payment,
                self.invoice,
                Decimal("0.00"),
                self.accountant,
            )

    def test_reverse_payment_recalculates_invoice(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        allocate_payment(
            completed_payment,
            self.invoice,
            Decimal("100000.00"),
            self.accountant,
        )

        reversed_payment = reverse_payment(
            completed_payment,
            self.accountant,
            reason="Duplicate payment.",
        )

        reversed_payment.refresh_from_db()
        self.invoice.refresh_from_db()

        self.assertEqual(
            reversed_payment.status,
            Payment.Status.REVERSED,
        )
        self.assertEqual(
            self.invoice.amount_paid,
            Decimal("0.00"),
        )
        self.assertEqual(
            self.invoice.balance,
            Decimal("100000.00"),
        )
        self.assertEqual(
            self.invoice.status,
            StudentInvoice.Status.ISSUED,
        )

    def test_reverse_payment_creates_transaction(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        reversed_payment = reverse_payment(
            completed_payment,
            self.accountant,
            reason="Wrong student.",
        )

        transaction = FinancialTransaction.objects.get(
            payment=reversed_payment,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_REVERSED
            ),
        )

        self.assertEqual(
            transaction.description,
            "Wrong student.",
        )
        self.assertEqual(
            transaction.metadata["reason"],
            "Wrong student.",
        )

    def test_cannot_reverse_pending_payment(self):
        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only completed payments can be reversed.",
        ):
            reverse_payment(
                self.payment,
                self.accountant,
            )

    def test_cancel_pending_payment(self):
        cancelled_payment = cancel_payment(
            self.payment,
            self.accountant,
            reason="Payment entered by mistake.",
        )

        cancelled_payment.refresh_from_db()

        self.assertEqual(
            cancelled_payment.status,
            Payment.Status.CANCELLED,
        )

        transaction = FinancialTransaction.objects.get(
            payment=cancelled_payment,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_CANCELLED
            ),
        )

        self.assertEqual(
            transaction.description,
            "Payment entered by mistake.",
        )

    def test_cannot_cancel_completed_payment(self):
        completed_payment = record_payment(
            self.payment,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only pending payments can be cancelled.",
        ):
            cancel_payment(
                completed_payment,
                self.accountant,
            )