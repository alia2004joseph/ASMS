from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from finance.models import (
    FinancialTransaction,
    Payment,
    PaymentAllocation,
    StudentInvoice,
)

from .factories import (
    create_academic_term,
    create_academic_year,
    create_accountant,
    create_admin,
    create_classroom,
    create_fee_category,
    create_fee_structure,
    create_invoice,
    create_invoice_item,
    create_payment,
    create_school,
    create_student,
)


class PaymentAPITests(APITestCase):
    """
    Tests payment creation, completion, allocation, cancellation,
    reversal, history and school isolation.
    """

    def setUp(self):
        # -------------------------------------------------------------
        # School one
        # -------------------------------------------------------------
        self.school_one = create_school(
            name="Payment School One",
            code="PAY-SCH-ONE",
        )

        self.admin_one = create_admin(
            self.school_one,
            email="payment.admin.one@test.com",
        )

        self.accountant_one = create_accountant(
            self.school_one,
            email="payment.accountant.one@test.com",
        )

        self.year_one = create_academic_year(self.school_one)

        self.term_one = create_academic_term(
            self.school_one,
            self.year_one,
        )

        self.classroom_one = create_classroom(
            self.school_one,
            self.year_one,
        )

        self.student_one = create_student(
            school=self.school_one,
            classroom=self.classroom_one,
            email="payment.student.one@test.com",
            student_id_number="PAY-STU-ONE",
        )

        self.fee_category_one = create_fee_category(
            self.school_one,
        )

        self.fee_structure_one = create_fee_structure(
            school=self.school_one,
            term=self.term_one,
            classroom=self.classroom_one,
            fee_category=self.fee_category_one,
            created_by=self.admin_one,
        )

        self.invoice_one = create_invoice(
            school=self.school_one,
            student=self.student_one,
            term=self.term_one,
            created_by=self.admin_one,
        )

        create_invoice_item(
            invoice=self.invoice_one,
            fee_structure=self.fee_structure_one,
        )

        # -------------------------------------------------------------
        # School two
        # -------------------------------------------------------------
        self.school_two = create_school(
            name="Payment School Two",
            code="PAY-SCH-TWO",
        )

        self.admin_two = create_admin(
            self.school_two,
            email="payment.admin.two@test.com",
        )

        self.accountant_two = create_accountant(
            self.school_two,
            email="payment.accountant.two@test.com",
        )

        self.year_two = create_academic_year(self.school_two)

        self.term_two = create_academic_term(
            self.school_two,
            self.year_two,
        )

        self.classroom_two = create_classroom(
            self.school_two,
            self.year_two,
        )

        self.student_two = create_student(
            school=self.school_two,
            classroom=self.classroom_two,
            email="payment.student.two@test.com",
            student_id_number="PAY-STU-TWO",
        )

        self.fee_category_two = create_fee_category(
            self.school_two,
        )

        self.fee_structure_two = create_fee_structure(
            school=self.school_two,
            term=self.term_two,
            classroom=self.classroom_two,
            fee_category=self.fee_category_two,
            created_by=self.admin_two,
        )

        self.invoice_two = create_invoice(
            school=self.school_two,
            student=self.student_two,
            term=self.term_two,
            created_by=self.admin_two,
        )

        create_invoice_item(
            invoice=self.invoice_two,
            fee_structure=self.fee_structure_two,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    @staticmethod
    def response_results(response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]

        return response.data

    def issue_invoice(self, invoice, user=None):
        self.authenticate(user or self.accountant_one)

        url = reverse(
            "student_invoice-issue",
            args=[invoice.pk],
        )

        response = self.client.post(
            url,
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        invoice.refresh_from_db()
        return response

    def complete_payment(self, payment, user=None):
        self.authenticate(user or self.accountant_one)

        url = reverse(
            "payment-complete",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        payment.refresh_from_db()
        return response

    # -----------------------------------------------------------------
    # Payment creation
    # -----------------------------------------------------------------

    def test_accountant_can_create_payment(self):
        self.authenticate(self.accountant_one)

        url = reverse("payment-list")

        payload = {
            "student": self.student_one.pk,
            "payment_reference": "PAY-API-001",
            "payment_date": "2026-01-15",
            "amount": "100000.00",
            "payment_method": "cash",
            "external_reference": "",
            "notes": "Created through the API.",
        }

        response = self.client.post(
            url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        payment = Payment.objects.get(
            payment_reference="PAY-API-001",
        )

        self.assertEqual(
            payment.school,
            self.school_one,
        )
        self.assertEqual(
            payment.student,
            self.student_one,
        )
        self.assertEqual(
            payment.received_by,
            self.accountant_one,
        )
        self.assertEqual(
            payment.status,
            Payment.Status.PENDING,
        )

    def test_payment_school_is_taken_from_authenticated_user(self):
        self.authenticate(self.accountant_one)

        url = reverse("payment-list")

        payload = {
            "school": self.school_two.pk,
            "student": self.student_one.pk,
            "payment_reference": "PAY-SCHOOL-OVERRIDE",
            "payment_date": "2026-01-15",
            "amount": "50000.00",
            "payment_method": "cash",
        }

        response = self.client.post(
            url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        payment = Payment.objects.get(
            payment_reference="PAY-SCHOOL-OVERRIDE",
        )

        self.assertEqual(
            payment.school,
            self.school_one,
        )

    def test_cannot_create_payment_for_student_from_another_school(self):
        self.authenticate(self.accountant_one)

        url = reverse("payment-list")

        payload = {
            "student": self.student_two.pk,
            "payment_reference": "PAY-FOREIGN-STUDENT",
            "payment_date": "2026-01-15",
            "amount": "50000.00",
            "payment_method": "cash",
        }

        response = self.client.post(
            url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "student",
            response.data,
        )

    def test_duplicate_payment_reference_is_rejected(self):
        create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-DUPLICATE",
        )

        self.authenticate(self.accountant_one)

        url = reverse("payment-list")

        payload = {
            "student": self.student_one.pk,
            "payment_reference": "PAY-DUPLICATE",
            "payment_date": "2026-01-15",
            "amount": "50000.00",
            "payment_method": "cash",
        }

        response = self.client.post(
            url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "payment_reference",
            response.data,
        )

    def test_negative_payment_amount_is_rejected(self):
        self.authenticate(self.accountant_one)

        url = reverse("payment-list")

        payload = {
            "student": self.student_one.pk,
            "payment_reference": "PAY-NEGATIVE",
            "payment_date": "2026-01-15",
            "amount": "-1000.00",
            "payment_method": "cash",
        }

        response = self.client.post(
            url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "amount",
            response.data,
        )

    # -----------------------------------------------------------------
    # Completion workflow
    # -----------------------------------------------------------------

    def test_pending_payment_can_be_completed(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-COMPLETE",
        )

        response = self.complete_payment(payment)

        self.assertEqual(
            payment.status,
            Payment.Status.COMPLETED,
        )

        # Confirms refresh_from_db() is used before serialization.
        self.assertEqual(
            response.data["status"],
            Payment.Status.COMPLETED,
        )

    def test_completing_payment_creates_financial_transaction(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.admin_one,
            payment_reference="PAY-TRANSACTION",
            amount=Decimal("75000.00"),
        )

        self.complete_payment(
            payment,
            user=self.admin_one,
        )

        transaction = FinancialTransaction.objects.get(
            payment=payment,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_RECORDED
            ),
        )

        self.assertEqual(
            transaction.school,
            self.school_one,
        )
        self.assertEqual(
            transaction.student,
            self.student_one,
        )
        self.assertEqual(
            transaction.amount,
            Decimal("75000.00"),
        )
        self.assertEqual(
            transaction.created_by,
            self.admin_one,
        )

    def test_payment_cannot_be_completed_twice(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-COMPLETE-TWICE",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-complete",
            args=[payment.pk],
        )

        second_response = self.client.post(
            url,
            {},
            format="json",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    # -----------------------------------------------------------------
    # Allocation workflow
    # -----------------------------------------------------------------

    def test_completed_payment_can_be_allocated_to_invoice(self):
        self.issue_invoice(self.invoice_one)

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-ALLOCATE",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "40000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        allocation = PaymentAllocation.objects.get(
            payment=payment,
            invoice=self.invoice_one,
        )

        self.assertEqual(
            allocation.amount,
            Decimal("40000.00"),
        )
        self.assertEqual(
            allocation.allocated_by,
            self.accountant_one,
        )

    def test_allocation_updates_invoice_balance_and_status(self):
        self.issue_invoice(self.invoice_one)

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-PARTIAL",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "40000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        self.invoice_one.refresh_from_db()

        self.assertEqual(
            self.invoice_one.amount_paid,
            Decimal("40000.00"),
        )
        self.assertEqual(
            self.invoice_one.balance,
            Decimal("60000.00"),
        )
        self.assertEqual(
            self.invoice_one.status,
            StudentInvoice.Status.PARTIALLY_PAID,
        )

    def test_full_allocation_marks_invoice_paid(self):
        self.issue_invoice(self.invoice_one)

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-FULL",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "100000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        self.invoice_one.refresh_from_db()

        self.assertEqual(
            self.invoice_one.amount_paid,
            Decimal("100000.00"),
        )
        self.assertEqual(
            self.invoice_one.balance,
            Decimal("0.00"),
        )
        self.assertEqual(
            self.invoice_one.status,
            StudentInvoice.Status.PAID,
        )

    def test_allocation_creates_financial_transaction(self):
        self.issue_invoice(self.invoice_one)

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-ALLOC-TX",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "25000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        transaction = FinancialTransaction.objects.get(
            payment=payment,
            invoice=self.invoice_one,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_ALLOCATED
            ),
        )

        self.assertEqual(
            transaction.amount,
            Decimal("25000.00"),
        )
        self.assertEqual(
            transaction.created_by,
            self.accountant_one,
        )

    def test_payment_cannot_be_overallocated(self):
        self.issue_invoice(self.invoice_one)

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-OVERALLOCATE",
            amount=Decimal("50000.00"),
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "60000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            PaymentAllocation.objects.filter(
                payment=payment,
            ).exists()
        )

    def test_pending_payment_cannot_be_allocated(self):
        self.issue_invoice(self.invoice_one)

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-PENDING-ALLOCATE",
        )

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "25000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_allocation_requires_invoice_and_amount(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-MISSING-DATA",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "detail",
            response.data,
        )

    def test_invalid_allocation_amount_is_rejected(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-INVALID-AMOUNT",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "not-a-number",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "amount",
            response.data,
        )

    def test_payment_cannot_be_allocated_to_another_school_invoice(self):
        self.issue_invoice(
            self.invoice_two,
            user=self.accountant_two,
        )

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-CROSS-SCHOOL",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "invoice": self.invoice_two.pk,
                "amount": "25000.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    # -----------------------------------------------------------------
    # Cancellation
    # -----------------------------------------------------------------

    def test_pending_payment_can_be_cancelled(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-CANCEL",
        )

        self.authenticate(self.accountant_one)

        url = reverse(
            "payment-cancel",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "reason": "Payment entered incorrectly.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            Payment.Status.CANCELLED,
        )
        self.assertEqual(
            response.data["status"],
            Payment.Status.CANCELLED,
        )

    def test_cancelling_payment_creates_financial_transaction(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.admin_one,
            payment_reference="PAY-CANCEL-TX",
            amount=Decimal("50000.00"),
        )

        self.authenticate(self.admin_one)

        url = reverse(
            "payment-cancel",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "reason": "Duplicate payment.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        transaction = FinancialTransaction.objects.get(
            payment=payment,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_CANCELLED
            ),
        )

        self.assertEqual(
            transaction.amount,
            Decimal("50000.00"),
        )
        self.assertEqual(
            transaction.created_by,
            self.admin_one,
        )
        self.assertEqual(
            transaction.description,
            "Duplicate payment.",
        )

    # -----------------------------------------------------------------
    # Reversal
    # -----------------------------------------------------------------

    def test_completed_payment_can_be_reversed(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-REVERSE",
        )

        self.complete_payment(payment)

        url = reverse(
            "payment-reverse",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "reason": "Bank reversed the transaction.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            Payment.Status.REVERSED,
        )
        self.assertEqual(
            response.data["status"],
            Payment.Status.REVERSED,
        )

    def test_reversing_allocated_payment_restores_invoice_balance(self):
        self.issue_invoice(self.invoice_one)

        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-REVERSE-ALLOC",
        )

        self.complete_payment(payment)

        allocate_url = reverse(
            "payment-allocate",
            args=[payment.pk],
        )

        allocate_response = self.client.post(
            allocate_url,
            {
                "invoice": self.invoice_one.pk,
                "amount": "40000.00",
            },
            format="json",
        )

        self.assertEqual(
            allocate_response.status_code,
            status.HTTP_201_CREATED,
            allocate_response.data,
        )

        reverse_url = reverse(
            "payment-reverse",
            args=[payment.pk],
        )

        reverse_response = self.client.post(
            reverse_url,
            {
                "reason": "Payment reversed.",
            },
            format="json",
        )

        self.assertEqual(
            reverse_response.status_code,
            status.HTTP_200_OK,
            reverse_response.data,
        )

        self.invoice_one.refresh_from_db()

        self.assertEqual(
            self.invoice_one.amount_paid,
            Decimal("0.00"),
        )
        self.assertEqual(
            self.invoice_one.balance,
            Decimal("100000.00"),
        )
        self.assertEqual(
            self.invoice_one.status,
            StudentInvoice.Status.ISSUED,
        )

    def test_reversing_payment_creates_financial_transaction(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.admin_one,
            payment_reference="PAY-REVERSE-TX",
            amount=Decimal("80000.00"),
        )

        self.complete_payment(
            payment,
            user=self.admin_one,
        )

        url = reverse(
            "payment-reverse",
            args=[payment.pk],
        )

        response = self.client.post(
            url,
            {
                "reason": "Transaction reversed by bank.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        transaction = FinancialTransaction.objects.get(
            payment=payment,
            transaction_type=(
                FinancialTransaction.TransactionType.PAYMENT_REVERSED
            ),
        )

        self.assertEqual(
            transaction.amount,
            Decimal("80000.00"),
        )
        self.assertEqual(
            transaction.created_by,
            self.admin_one,
        )

    # -----------------------------------------------------------------
    # Read access and history
    # -----------------------------------------------------------------

    def test_student_can_view_own_payment(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-STUDENT-VIEW",
        )

        self.authenticate(self.student_one.user)

        url = reverse(
            "payment-detail",
            args=[payment.pk],
        )

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["id"],
            payment.pk,
        )

    def test_student_cannot_view_another_students_payment(self):
        foreign_payment = create_payment(
            school=self.school_two,
            student=self.student_two,
            received_by=self.accountant_two,
            payment_reference="PAY-FOREIGN-VIEW",
        )

        self.authenticate(self.student_one.user)

        url = reverse(
            "payment-detail",
            args=[foreign_payment.pk],
        )

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_payment_history_can_filter_by_student(self):
        own_payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-HISTORY-ONE",
        )

        other_student = create_student(
            school=self.school_one,
            classroom=self.classroom_one,
            email="history.other@test.com",
            student_id_number="PAY-STU-OTHER",
        )

        other_payment = create_payment(
            school=self.school_one,
            student=other_student,
            received_by=self.accountant_one,
            payment_reference="PAY-HISTORY-TWO",
        )

        self.authenticate(self.accountant_one)

        url = reverse("payment-history")

        response = self.client.get(
            url,
            {
                "student": self.student_one.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        results = self.response_results(response)
        returned_ids = {item["id"] for item in results}

        self.assertIn(
            own_payment.pk,
            returned_ids,
        )
        self.assertNotIn(
            other_payment.pk,
            returned_ids,
        )

    # -----------------------------------------------------------------
    # School isolation and deletion protection
    # -----------------------------------------------------------------

    def test_accountant_cannot_access_another_schools_payment(self):
        foreign_payment = create_payment(
            school=self.school_two,
            student=self.student_two,
            received_by=self.accountant_two,
            payment_reference="PAY-OTHER-SCHOOL",
        )

        self.authenticate(self.accountant_one)

        url = reverse(
            "payment-detail",
            args=[foreign_payment.pk],
        )

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_payment_cannot_be_deleted(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="PAY-NO-DELETE",
        )

        self.authenticate(self.accountant_one)

        url = reverse(
            "payment-detail",
            args=[payment.pk],
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertTrue(
            Payment.objects.filter(
                pk=payment.pk,
            ).exists()
        )