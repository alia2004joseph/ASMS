from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from finance.models import (
    Expense,
    ExpenseCategory,
    FinancialTransaction,
)

from .factories import (
    create_accountant,
    create_admin,
    create_school,
)


class ExpenseAPITests(APITestCase):
    """
    Tests expense creation, workflow transitions, audit entries,
    validation and school isolation.
    """

    def setUp(self):
        # -------------------------------------------------------------
        # School one
        # -------------------------------------------------------------
        self.school_one = create_school(
            name="Expense School One",
            code="EXP-SCH-ONE",
        )

        self.admin_one = create_admin(
            self.school_one,
            email="expense.admin.one@test.com",
        )

        self.accountant_one = create_accountant(
            self.school_one,
            email="expense.accountant.one@test.com",
        )

        self.category_one = ExpenseCategory.objects.create(
            school=self.school_one,
            name="Utilities",
            code="UTILITIES",
            description="Electricity and water expenses.",
            is_active=True,
        )

        # -------------------------------------------------------------
        # School two
        # -------------------------------------------------------------
        self.school_two = create_school(
            name="Expense School Two",
            code="EXP-SCH-TWO",
        )

        self.admin_two = create_admin(
            self.school_two,
            email="expense.admin.two@test.com",
        )

        self.accountant_two = create_accountant(
            self.school_two,
            email="expense.accountant.two@test.com",
        )

        self.category_two = ExpenseCategory.objects.create(
            school=self.school_two,
            name="Transport",
            code="TRANSPORT",
            description="School transport expenses.",
            is_active=True,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    @staticmethod
    def response_results(response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]

        return response.data

    def create_expense_object(
        self,
        *,
        school=None,
        category=None,
        recorded_by=None,
        description="Electricity bill",
        amount=Decimal("100000.00"),
        reference="EXP-001",
        status_value=Expense.Status.DRAFT,
    ):
        school = school or self.school_one
        category = category or self.category_one
        recorded_by = recorded_by or self.accountant_one

        return Expense.objects.create(
            school=school,
            category=category,
            description=description,
            amount=amount,
            expense_date="2026-07-18",
            payment_method="cash",
            reference=reference,
            status=status_value,
            recorded_by=recorded_by,
        )

    def perform_action(
        self,
        expense,
        action_name,
        *,
        user=None,
        data=None,
        expected_status=status.HTTP_200_OK,
    ):
        self.authenticate(user or self.accountant_one)

        url = reverse(
            f"expense-{action_name}",
            args=[expense.pk],
        )

        response = self.client.post(
            url,
            data or {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            expected_status,
            response.data,
        )

        expense.refresh_from_db()
        return response

    def submit_expense(self, expense, user=None):
        return self.perform_action(
            expense,
            "submit",
            user=user,
        )

    def approve_expense(self, expense, user=None):
        return self.perform_action(
            expense,
            "approve",
            user=user,
        )

    # -----------------------------------------------------------------
    # Creation
    # -----------------------------------------------------------------

    def test_accountant_can_create_expense(self):
        self.authenticate(self.accountant_one)

        response = self.client.post(
            reverse("expense-list"),
            {
                "category": self.category_one.pk,
                "description": "Internet subscription",
                "amount": "150000.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "reference": "EXP-API-001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        expense = Expense.objects.get(
            reference="EXP-API-001",
        )

        self.assertEqual(expense.school, self.school_one)
        self.assertEqual(expense.recorded_by, self.accountant_one)
        self.assertEqual(expense.category, self.category_one)
        self.assertEqual(expense.status, Expense.Status.DRAFT)
        self.assertEqual(expense.amount, Decimal("150000.00"))

    def test_admin_can_create_expense(self):
        self.authenticate(self.admin_one)

        response = self.client.post(
            reverse("expense-list"),
            {
                "category": self.category_one.pk,
                "description": "Water bill",
                "amount": "80000.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "reference": "EXP-ADMIN-001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        expense = Expense.objects.get(
            reference="EXP-ADMIN-001",
        )

        self.assertEqual(expense.recorded_by, self.admin_one)
        self.assertEqual(expense.school, self.school_one)

    def test_authenticated_users_school_is_assigned_automatically(self):
        self.authenticate(self.accountant_one)

        response = self.client.post(
            reverse("expense-list"),
            {
                "school": self.school_two.pk,
                "category": self.category_one.pk,
                "description": "Cleaning supplies",
                "amount": "45000.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "reference": "EXP-SCHOOL-AUTO",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        expense = Expense.objects.get(
            reference="EXP-SCHOOL-AUTO",
        )

        self.assertEqual(expense.school, self.school_one)

    def test_cannot_use_category_from_another_school(self):
        self.authenticate(self.accountant_one)

        response = self.client.post(
            reverse("expense-list"),
            {
                "category": self.category_two.pk,
                "description": "Foreign category expense",
                "amount": "50000.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "reference": "EXP-FOREIGN-CATEGORY",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("category", response.data)

    def test_negative_expense_amount_is_rejected(self):
        self.authenticate(self.accountant_one)

        response = self.client.post(
            reverse("expense-list"),
            {
                "category": self.category_one.pk,
                "description": "Invalid expense",
                "amount": "-5000.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "reference": "EXP-NEGATIVE",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("amount", response.data)

    # -----------------------------------------------------------------
    # Submission
    # -----------------------------------------------------------------

    def test_draft_expense_can_be_submitted(self):
        expense = self.create_expense_object(
            reference="EXP-SUBMIT",
        )

        response = self.submit_expense(expense)

        self.assertEqual(
            expense.status,
            Expense.Status.SUBMITTED,
        )
        self.assertEqual(
            response.data["status"],
            Expense.Status.SUBMITTED,
        )

    def test_expense_cannot_be_submitted_twice(self):
        expense = self.create_expense_object(
            reference="EXP-SUBMIT-TWICE",
        )

        self.submit_expense(expense)

        self.perform_action(
            expense,
            "submit",
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    # -----------------------------------------------------------------
    # Approval
    # -----------------------------------------------------------------

    def test_submitted_expense_can_be_approved(self):
        expense = self.create_expense_object(
            reference="EXP-APPROVE",
        )

        self.submit_expense(expense)

        response = self.approve_expense(
            expense,
            user=self.admin_one,
        )

        self.assertEqual(
            expense.status,
            Expense.Status.APPROVED,
        )
        self.assertEqual(
            expense.approved_by,
            self.admin_one,
        )
        self.assertIsNotNone(expense.approved_at)

        self.assertEqual(
            response.data["status"],
            Expense.Status.APPROVED,
        )

    def test_approving_expense_creates_financial_transaction(self):
        expense = self.create_expense_object(
            reference="EXP-APPROVE-TX",
            amount=Decimal("120000.00"),
        )

        self.submit_expense(expense)

        self.approve_expense(
            expense,
            user=self.admin_one,
        )

        transaction = FinancialTransaction.objects.get(
            expense=expense,
            transaction_type=(
                FinancialTransaction.TransactionType.EXPENSE_APPROVED
            ),
        )

        self.assertEqual(transaction.school, self.school_one)
        self.assertEqual(transaction.amount, Decimal("120000.00"))
        self.assertEqual(transaction.created_by, self.admin_one)
        self.assertEqual(transaction.reference, "EXP-APPROVE-TX")

    def test_draft_expense_cannot_be_approved(self):
        expense = self.create_expense_object(
            reference="EXP-DRAFT-APPROVE",
        )

        self.perform_action(
            expense,
            "approve",
            user=self.admin_one,
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.DRAFT)

    # -----------------------------------------------------------------
    # Rejection
    # -----------------------------------------------------------------

    def test_submitted_expense_can_be_rejected(self):
        expense = self.create_expense_object(
            reference="EXP-REJECT",
        )

        self.submit_expense(expense)

        response = self.perform_action(
            expense,
            "reject",
            user=self.admin_one,
            data={"reason": "Supporting documents are missing."},
        )

        self.assertEqual(
            expense.status,
            Expense.Status.REJECTED,
        )
        self.assertIsNone(expense.approved_by)
        self.assertIsNone(expense.approved_at)

        self.assertEqual(
            response.data["status"],
            Expense.Status.REJECTED,
        )

    def test_draft_expense_cannot_be_rejected(self):
        expense = self.create_expense_object(
            reference="EXP-DRAFT-REJECT",
        )

        self.perform_action(
            expense,
            "reject",
            user=self.admin_one,
            data={"reason": "Invalid request."},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.DRAFT)

    # -----------------------------------------------------------------
    # Mark paid
    # -----------------------------------------------------------------

    def test_approved_expense_can_be_marked_paid(self):
        expense = self.create_expense_object(
            reference="EXP-MARK-PAID",
        )

        self.submit_expense(expense)
        self.approve_expense(
            expense,
            user=self.admin_one,
        )

        response = self.perform_action(
            expense,
            "mark-paid",
            user=self.accountant_one,
        )

        self.assertEqual(
            expense.status,
            Expense.Status.PAID,
        )
        self.assertEqual(
            response.data["status"],
            Expense.Status.PAID,
        )

    def test_marking_expense_paid_creates_financial_transaction(self):
        expense = self.create_expense_object(
            reference="EXP-PAID-TX",
            amount=Decimal("200000.00"),
        )

        self.submit_expense(expense)
        self.approve_expense(
            expense,
            user=self.admin_one,
        )

        self.perform_action(
            expense,
            "mark-paid",
            user=self.accountant_one,
        )

        transaction = FinancialTransaction.objects.get(
            expense=expense,
            transaction_type=(
                FinancialTransaction.TransactionType.EXPENSE_RECORDED
            ),
        )

        self.assertEqual(transaction.school, self.school_one)
        self.assertEqual(transaction.amount, Decimal("200000.00"))
        self.assertEqual(transaction.created_by, self.accountant_one)
        self.assertEqual(transaction.reference, "EXP-PAID-TX")

    def test_draft_expense_cannot_be_marked_paid(self):
        expense = self.create_expense_object(
            reference="EXP-DRAFT-PAID",
        )

        self.perform_action(
            expense,
            "mark-paid",
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.DRAFT)

    # -----------------------------------------------------------------
    # Cancellation
    # -----------------------------------------------------------------

    def test_draft_expense_can_be_cancelled(self):
        expense = self.create_expense_object(
            reference="EXP-CANCEL",
        )

        response = self.perform_action(
            expense,
            "cancel",
            data={"reason": "Expense was entered by mistake."},
        )

        self.assertEqual(
            expense.status,
            Expense.Status.CANCELLED,
        )
        self.assertEqual(
            response.data["status"],
            Expense.Status.CANCELLED,
        )

    def test_paid_expense_cannot_be_cancelled(self):
        expense = self.create_expense_object(
            reference="EXP-PAID-CANCEL",
        )

        self.submit_expense(expense)
        self.approve_expense(
            expense,
            user=self.admin_one,
        )
        self.perform_action(
            expense,
            "mark-paid",
            user=self.accountant_one,
        )

        self.perform_action(
            expense,
            "cancel",
            user=self.admin_one,
            data={"reason": "Attempted cancellation."},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.PAID)

    def test_cancelled_expense_cannot_be_cancelled_again(self):
        expense = self.create_expense_object(
            reference="EXP-CANCEL-TWICE",
        )

        self.perform_action(
            expense,
            "cancel",
        )

        self.perform_action(
            expense,
            "cancel",
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    # -----------------------------------------------------------------
    # School isolation
    # -----------------------------------------------------------------

    def test_accountant_only_sees_own_school_expenses(self):
        own_expense = self.create_expense_object(
            reference="EXP-LIST-OWN",
        )

        foreign_expense = self.create_expense_object(
            school=self.school_two,
            category=self.category_two,
            recorded_by=self.accountant_two,
            reference="EXP-LIST-FOREIGN",
        )

        self.authenticate(self.accountant_one)

        response = self.client.get(
            reverse("expense-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        results = self.response_results(response)
        returned_ids = {item["id"] for item in results}

        self.assertIn(own_expense.pk, returned_ids)
        self.assertNotIn(foreign_expense.pk, returned_ids)

    def test_accountant_cannot_access_foreign_expense(self):
        foreign_expense = self.create_expense_object(
            school=self.school_two,
            category=self.category_two,
            recorded_by=self.accountant_two,
            reference="EXP-FOREIGN-DETAIL",
        )

        self.authenticate(self.accountant_one)

        response = self.client.get(
            reverse(
                "expense-detail",
                args=[foreign_expense.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_accountant_cannot_run_action_on_foreign_expense(self):
        foreign_expense = self.create_expense_object(
            school=self.school_two,
            category=self.category_two,
            recorded_by=self.accountant_two,
            reference="EXP-FOREIGN-ACTION",
        )

        self.authenticate(self.accountant_one)

        response = self.client.post(
            reverse(
                "expense-submit",
                args=[foreign_expense.pk],
            ),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        foreign_expense.refresh_from_db()
        self.assertEqual(
            foreign_expense.status,
            Expense.Status.DRAFT,
        )