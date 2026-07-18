from decimal import Decimal

from django.test import TestCase

from finance.models import (
    FinancialTransaction,
    StudentInvoice,
)
from finance.services import (
    FinanceServiceError,
    cancel_invoice,
    issue_invoice,
    recalculate_invoice_totals,
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
    create_school,
    create_student,
)


class InvoiceServiceTests(TestCase):
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

    def add_invoice_item(self):
        return create_invoice_item(
            self.invoice,
            self.fee_structure,
        )

    def test_recalculate_invoice_totals_from_items(self):
        self.add_invoice_item()

        result = recalculate_invoice_totals(self.invoice)

        self.invoice.refresh_from_db()

        self.assertEqual(result.pk, self.invoice.pk)
        self.assertEqual(
            self.invoice.subtotal,
            Decimal("100000.00"),
        )
        self.assertEqual(
            self.invoice.total_amount,
            Decimal("100000.00"),
        )

    def test_recalculate_totals_applies_discount_and_adjustment(self):
        self.add_invoice_item()

        self.invoice.discount_amount = Decimal("10000.00")
        self.invoice.adjustment_amount = Decimal("5000.00")

        result = recalculate_invoice_totals(
            self.invoice,
            save=False,
        )

        self.assertEqual(
            result.subtotal,
            Decimal("100000.00"),
        )
        self.assertEqual(
            result.total_amount,
            Decimal("95000.00"),
        )

        # save=False means the database values remain unchanged.
        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.total_amount,
            Decimal("0.00"),
        )

    def test_recalculate_totals_rejects_negative_total(self):
        self.add_invoice_item()

        self.invoice.discount_amount = Decimal("150000.00")
        self.invoice.adjustment_amount = Decimal("0.00")

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Invoice total cannot be negative",
        ):
            recalculate_invoice_totals(
                self.invoice,
                save=False,
            )

    def test_issue_invoice_updates_financial_state(self):
        self.add_invoice_item()

        issued_invoice = issue_invoice(
            self.invoice,
            self.accountant,
        )

        issued_invoice.refresh_from_db()

        self.assertEqual(
            issued_invoice.status,
            StudentInvoice.Status.ISSUED,
        )
        self.assertEqual(
            issued_invoice.subtotal,
            Decimal("100000.00"),
        )
        self.assertEqual(
            issued_invoice.total_amount,
            Decimal("100000.00"),
        )
        self.assertEqual(
            issued_invoice.amount_paid,
            Decimal("0.00"),
        )
        self.assertEqual(
            issued_invoice.balance,
            Decimal("100000.00"),
        )

    def test_issue_invoice_creates_financial_transaction(self):
        self.add_invoice_item()

        issued_invoice = issue_invoice(
            self.invoice,
            self.accountant,
        )

        transaction = FinancialTransaction.objects.get(
            invoice=issued_invoice,
            transaction_type=(
                FinancialTransaction.TransactionType.INVOICE_ISSUED
            ),
        )

        self.assertEqual(transaction.school, self.school)
        self.assertEqual(transaction.student, self.student)
        self.assertEqual(transaction.amount, Decimal("100000.00"))
        self.assertEqual(transaction.created_by, self.accountant)
        self.assertEqual(
            transaction.reference,
            issued_invoice.invoice_number,
        )

    def test_cannot_issue_invoice_without_items(self):
        with self.assertRaisesMessage(
            FinanceServiceError,
            "Cannot issue an invoice with no items.",
        ):
            issue_invoice(
                self.invoice,
                self.accountant,
            )

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            StudentInvoice.Status.DRAFT,
        )

        self.assertFalse(
            FinancialTransaction.objects.filter(
                invoice=self.invoice,
            ).exists()
        )

    def test_cannot_issue_invoice_twice(self):
        self.add_invoice_item()

        issue_invoice(
            self.invoice,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only draft invoices can be issued.",
        ):
            issue_invoice(
                self.invoice,
                self.accountant,
            )

        issued_transactions = FinancialTransaction.objects.filter(
            invoice=self.invoice,
            transaction_type=(
                FinancialTransaction.TransactionType.INVOICE_ISSUED
            ),
        )

        self.assertEqual(issued_transactions.count(), 1)

    def test_user_from_another_school_cannot_issue_invoice(self):
        other_school = create_school(
            name="Other School",
            code="OTHER",
        )

        other_accountant = create_accountant(
            other_school,
            email="other-accountant@test.com",
        )

        self.add_invoice_item()

        with self.assertRaisesMessage(
            FinanceServiceError,
            "You cannot perform this finance action for another school.",
        ):
            issue_invoice(
                self.invoice,
                other_accountant,
            )

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            StudentInvoice.Status.DRAFT,
        )

    def test_cancel_invoice_updates_status_and_creates_transaction(self):
        self.add_invoice_item()

        issued_invoice = issue_invoice(
            self.invoice,
            self.accountant,
        )

        cancelled_invoice = cancel_invoice(
            issued_invoice,
            self.accountant,
            reason="Invoice created incorrectly.",
        )

        cancelled_invoice.refresh_from_db()

        self.assertEqual(
            cancelled_invoice.status,
            StudentInvoice.Status.CANCELLED,
        )

        transaction = FinancialTransaction.objects.get(
            invoice=cancelled_invoice,
            transaction_type=(
                FinancialTransaction.TransactionType.INVOICE_CANCELLED
            ),
        )

        self.assertEqual(
            transaction.description,
            "Invoice created incorrectly.",
        )
        self.assertEqual(
            transaction.metadata["reason"],
            "Invoice created incorrectly.",
        )
        self.assertEqual(
            transaction.created_by,
            self.accountant,
        )

    def test_cannot_cancel_paid_invoice(self):
        self.add_invoice_item()

        issued_invoice = issue_invoice(
            self.invoice,
            self.accountant,
        )

        issued_invoice.status = StudentInvoice.Status.PAID
        issued_invoice.amount_paid = issued_invoice.total_amount
        issued_invoice.balance = Decimal("0.00")
        issued_invoice.save(
            update_fields=[
                "status",
                "amount_paid",
                "balance",
                "updated_at",
            ]
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Paid invoices cannot be cancelled.",
        ):
            cancel_invoice(
                issued_invoice,
                self.accountant,
            )

        issued_invoice.refresh_from_db()

        self.assertEqual(
            issued_invoice.status,
            StudentInvoice.Status.PAID,
        )

    def test_cannot_cancel_invoice_twice(self):
        self.add_invoice_item()

        issued_invoice = issue_invoice(
            self.invoice,
            self.accountant,
        )

        cancel_invoice(
            issued_invoice,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "This invoice is already cancelled.",
        ):
            cancel_invoice(
                issued_invoice,
                self.accountant,
            )

        cancellation_transactions = FinancialTransaction.objects.filter(
            invoice=issued_invoice,
            transaction_type=(
                FinancialTransaction.TransactionType.INVOICE_CANCELLED
            ),
        )

        self.assertEqual(cancellation_transactions.count(), 1)