from decimal import Decimal

from django.test import TestCase

from finance.models import Expense, FinancialTransaction
from finance.services import (
    FinanceServiceError,
    approve_expense,
    cancel_expense,
    mark_expense_paid,
    reject_expense,
    submit_expense,
)

from .factories import (
    create_accountant,
    create_expense,
    create_expense_category,
    create_school,
)


class ExpenseServiceTests(TestCase):
    def setUp(self):
        self.school = create_school()
        self.accountant = create_accountant(self.school)

        self.category = create_expense_category(
            self.school,
        )

        self.expense = create_expense(
            self.school,
            self.category,
            self.accountant,
        )

    def submit_current_expense(self):
        return submit_expense(
            self.expense,
            self.accountant,
        )

    def approve_current_expense(self):
        submitted_expense = self.submit_current_expense()

        return approve_expense(
            submitted_expense,
            self.accountant,
        )

    def test_submit_draft_expense(self):
        submitted_expense = submit_expense(
            self.expense,
            self.accountant,
        )

        submitted_expense.refresh_from_db()

        self.assertEqual(
            submitted_expense.status,
            Expense.Status.SUBMITTED,
        )

        self.assertIsNone(
            submitted_expense.approved_by,
        )

        self.assertIsNone(
            submitted_expense.approved_at,
        )

    def test_cannot_submit_expense_twice(self):
        submitted_expense = self.submit_current_expense()

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only draft expenses can be submitted.",
        ):
            submit_expense(
                submitted_expense,
                self.accountant,
            )

        submitted_expense.refresh_from_db()

        self.assertEqual(
            submitted_expense.status,
            Expense.Status.SUBMITTED,
        )

    def test_other_school_user_cannot_submit_expense(self):
        other_school = create_school(
            name="Other School",
            code="OTHER",
        )

        other_accountant = create_accountant(
            other_school,
            email="other-expense-accountant@test.com",
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "You cannot perform this finance action for another school.",
        ):
            submit_expense(
                self.expense,
                other_accountant,
            )

        self.expense.refresh_from_db()

        self.assertEqual(
            self.expense.status,
            Expense.Status.DRAFT,
        )

    def test_approve_submitted_expense(self):
        submitted_expense = self.submit_current_expense()

        approved_expense = approve_expense(
            submitted_expense,
            self.accountant,
        )

        approved_expense.refresh_from_db()

        self.assertEqual(
            approved_expense.status,
            Expense.Status.APPROVED,
        )

        self.assertEqual(
            approved_expense.approved_by,
            self.accountant,
        )

        self.assertIsNotNone(
            approved_expense.approved_at,
        )

    def test_approve_expense_creates_transaction(self):
        submitted_expense = self.submit_current_expense()

        approved_expense = approve_expense(
            submitted_expense,
            self.accountant,
        )

        transaction = FinancialTransaction.objects.get(
            expense=approved_expense,
            transaction_type=(
                FinancialTransaction.TransactionType.EXPENSE_APPROVED
            ),
        )

        self.assertEqual(
            transaction.school,
            self.school,
        )

        self.assertEqual(
            transaction.amount,
            Decimal("25000.00"),
        )

        self.assertEqual(
            transaction.created_by,
            self.accountant,
        )

        self.assertEqual(
            transaction.description,
            "Expense 'Electricity' approved.",
        )

        self.assertIn(
            "approved_at",
            transaction.metadata,
        )

    def test_cannot_approve_draft_expense(self):
        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only submitted expenses can be approved.",
        ):
            approve_expense(
                self.expense,
                self.accountant,
            )

        self.expense.refresh_from_db()

        self.assertEqual(
            self.expense.status,
            Expense.Status.DRAFT,
        )

        self.assertFalse(
            FinancialTransaction.objects.filter(
                expense=self.expense,
                transaction_type=(
                    FinancialTransaction.TransactionType.EXPENSE_APPROVED
                ),
            ).exists()
        )

    def test_cannot_approve_expense_twice(self):
        approved_expense = self.approve_current_expense()

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only submitted expenses can be approved.",
        ):
            approve_expense(
                approved_expense,
                self.accountant,
            )

        transactions = FinancialTransaction.objects.filter(
            expense=approved_expense,
            transaction_type=(
                FinancialTransaction.TransactionType.EXPENSE_APPROVED
            ),
        )

        self.assertEqual(
            transactions.count(),
            1,
        )

    def test_reject_submitted_expense(self):
        submitted_expense = self.submit_current_expense()

        rejected_expense = reject_expense(
            submitted_expense,
            self.accountant,
            reason="The amount is unsupported.",
        )

        rejected_expense.refresh_from_db()

        self.assertEqual(
            rejected_expense.status,
            Expense.Status.REJECTED,
        )

        self.assertIsNone(
            rejected_expense.approved_by,
        )

        self.assertIsNone(
            rejected_expense.approved_at,
        )

    def test_cannot_reject_draft_expense(self):
        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only submitted expenses can be rejected.",
        ):
            reject_expense(
                self.expense,
                self.accountant,
            )

        self.expense.refresh_from_db()

        self.assertEqual(
            self.expense.status,
            Expense.Status.DRAFT,
        )

    def test_cannot_reject_approved_expense(self):
        approved_expense = self.approve_current_expense()

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only submitted expenses can be rejected.",
        ):
            reject_expense(
                approved_expense,
                self.accountant,
            )

        approved_expense.refresh_from_db()

        self.assertEqual(
            approved_expense.status,
            Expense.Status.APPROVED,
        )

    def test_mark_approved_expense_as_paid(self):
        approved_expense = self.approve_current_expense()

        paid_expense = mark_expense_paid(
            approved_expense,
            self.accountant,
        )

        paid_expense.refresh_from_db()

        self.assertEqual(
            paid_expense.status,
            Expense.Status.PAID,
        )

        self.assertEqual(
            paid_expense.approved_by,
            self.accountant,
        )

        self.assertIsNotNone(
            paid_expense.approved_at,
        )

    def test_mark_expense_paid_creates_transaction(self):
        approved_expense = self.approve_current_expense()

        paid_expense = mark_expense_paid(
            approved_expense,
            self.accountant,
        )

        transaction = FinancialTransaction.objects.get(
            expense=paid_expense,
            transaction_type=(
                FinancialTransaction.TransactionType.EXPENSE_RECORDED
            ),
        )

        self.assertEqual(
            transaction.school,
            self.school,
        )

        self.assertEqual(
            transaction.amount,
            Decimal("25000.00"),
        )

        self.assertEqual(
            transaction.created_by,
            self.accountant,
        )

        self.assertEqual(
            transaction.metadata["event"],
            "expense_paid",
        )

        self.assertEqual(
            transaction.description,
            "Expense 'Electricity' marked as paid.",
        )

    def test_cannot_mark_draft_expense_as_paid(self):
        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only approved expenses can be marked as paid.",
        ):
            mark_expense_paid(
                self.expense,
                self.accountant,
            )

        self.expense.refresh_from_db()

        self.assertEqual(
            self.expense.status,
            Expense.Status.DRAFT,
        )

    def test_cannot_mark_submitted_expense_as_paid(self):
        submitted_expense = self.submit_current_expense()

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only approved expenses can be marked as paid.",
        ):
            mark_expense_paid(
                submitted_expense,
                self.accountant,
            )

        submitted_expense.refresh_from_db()

        self.assertEqual(
            submitted_expense.status,
            Expense.Status.SUBMITTED,
        )

    def test_cancel_draft_expense(self):
        cancelled_expense = cancel_expense(
            self.expense,
            self.accountant,
            reason="Expense entered incorrectly.",
        )

        cancelled_expense.refresh_from_db()

        self.assertEqual(
            cancelled_expense.status,
            Expense.Status.CANCELLED,
        )

    def test_cancel_submitted_expense(self):
        submitted_expense = self.submit_current_expense()

        cancelled_expense = cancel_expense(
            submitted_expense,
            self.accountant,
        )

        cancelled_expense.refresh_from_db()

        self.assertEqual(
            cancelled_expense.status,
            Expense.Status.CANCELLED,
        )

    def test_cancel_approved_expense(self):
        approved_expense = self.approve_current_expense()

        cancelled_expense = cancel_expense(
            approved_expense,
            self.accountant,
        )

        cancelled_expense.refresh_from_db()

        self.assertEqual(
            cancelled_expense.status,
            Expense.Status.CANCELLED,
        )

    def test_cannot_cancel_paid_expense(self):
        approved_expense = self.approve_current_expense()

        paid_expense = mark_expense_paid(
            approved_expense,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Paid expenses cannot be cancelled.",
        ):
            cancel_expense(
                paid_expense,
                self.accountant,
            )

        paid_expense.refresh_from_db()

        self.assertEqual(
            paid_expense.status,
            Expense.Status.PAID,
        )

    def test_cannot_cancel_expense_twice(self):
        cancelled_expense = cancel_expense(
            self.expense,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "This expense is already cancelled.",
        ):
            cancel_expense(
                cancelled_expense,
                self.accountant,
            )

        cancelled_expense.refresh_from_db()

        self.assertEqual(
            cancelled_expense.status,
            Expense.Status.CANCELLED,
        )

    def test_other_school_user_cannot_approve_expense(self):
        submitted_expense = self.submit_current_expense()

        other_school = create_school(
            name="Second School",
            code="SECOND",
        )

        other_accountant = create_accountant(
            other_school,
            email="second-expense-accountant@test.com",
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "You cannot perform this finance action for another school.",
        ):
            approve_expense(
                submitted_expense,
                other_accountant,
            )

        submitted_expense.refresh_from_db()

        self.assertEqual(
            submitted_expense.status,
            Expense.Status.SUBMITTED,
        )

        self.assertIsNone(
            submitted_expense.approved_by,
        )