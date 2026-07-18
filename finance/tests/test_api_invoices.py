from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from finance.models import FinancialTransaction, StudentInvoice

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
    create_school,
    create_student,
)


class StudentInvoiceAPITests(APITestCase):
    """
    Tests StudentInvoice API creation, validation, school isolation,
    issuing and cancellation workflows.
    """

    def setUp(self):
        # -------------------------------------------------------------
        # School one
        # -------------------------------------------------------------
        self.school_one = create_school(
            name="Invoice School One",
            code="INV-SCH-ONE",
        )

        self.admin_one = create_admin(
            self.school_one,
            email="invoice.admin.one@test.com",
        )

        self.accountant_one = create_accountant(
            self.school_one,
            email="invoice.accountant.one@test.com",
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
            email="invoice.student.one@test.com",
            student_id_number="INV-STU-ONE",
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

        # -------------------------------------------------------------
        # School two
        # -------------------------------------------------------------
        self.school_two = create_school(
            name="Invoice School Two",
            code="INV-SCH-TWO",
        )

        self.admin_two = create_admin(
            self.school_two,
            email="invoice.admin.two@test.com",
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
            email="invoice.student.two@test.com",
            student_id_number="INV-STU-TWO",
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    # -----------------------------------------------------------------
    # Invoice creation
    # -----------------------------------------------------------------

    def test_accountant_can_create_invoice(self):
        self.authenticate(self.accountant_one)

        url = reverse("student_invoice-list")

        payload = {
            "student": self.student_one.pk,
            "academic_term": self.term_one.pk,
            "invoice_number": "INV-API-001",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "discount_amount": "0.00",
            "adjustment_amount": "0.00",
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

        invoice = StudentInvoice.objects.get(
            invoice_number="INV-API-001",
        )

        self.assertEqual(
            invoice.school,
            self.school_one,
        )
        self.assertEqual(
            invoice.created_by,
            self.accountant_one,
        )
        self.assertEqual(
            invoice.student,
            self.student_one,
        )
        self.assertEqual(
            invoice.status,
            StudentInvoice.Status.DRAFT,
        )

    def test_non_superuser_cannot_assign_invoice_to_another_school(self):
        self.authenticate(self.accountant_one)

        url = reverse("student_invoice-list")

        payload = {
            "school": self.school_two.pk,
            "student": self.student_one.pk,
            "academic_term": self.term_one.pk,
            "invoice_number": "INV-SCHOOL-OVERRIDE",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "discount_amount": "0.00",
            "adjustment_amount": "0.00",
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

        invoice = StudentInvoice.objects.get(
            invoice_number="INV-SCHOOL-OVERRIDE",
        )

        # The school must come from the authenticated accountant.
        self.assertEqual(
            invoice.school,
            self.school_one,
        )

    # -----------------------------------------------------------------
    # Cross-school validation
    # -----------------------------------------------------------------

    def test_cannot_create_invoice_for_student_from_another_school(self):
        self.authenticate(self.accountant_one)

        url = reverse("student_invoice-list")

        payload = {
            "student": self.student_two.pk,
            "academic_term": self.term_one.pk,
            "invoice_number": "INV-FOREIGN-STUDENT",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "discount_amount": "0.00",
            "adjustment_amount": "0.00",
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

        self.assertFalse(
            StudentInvoice.objects.filter(
                invoice_number="INV-FOREIGN-STUDENT",
            ).exists()
        )

    def test_cannot_create_invoice_with_term_from_another_school(self):
        self.authenticate(self.accountant_one)

        url = reverse("student_invoice-list")

        payload = {
            "student": self.student_one.pk,
            "academic_term": self.term_two.pk,
            "invoice_number": "INV-FOREIGN-TERM",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "discount_amount": "0.00",
            "adjustment_amount": "0.00",
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
            "academic_term",
            response.data,
        )

    # -----------------------------------------------------------------
    # Invoice number validation
    # -----------------------------------------------------------------

    def test_duplicate_invoice_number_in_same_school_is_rejected(self):
        self.authenticate(self.accountant_one)

        url = reverse("student_invoice-list")

        payload = {
            "student": self.student_one.pk,
            "academic_term": self.term_one.pk,

            # The factory-created invoice already uses this number.
            "invoice_number": "INV-001",

            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "discount_amount": "0.00",
            "adjustment_amount": "0.00",
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
            "invoice_number",
            response.data,
        )

    def test_negative_discount_is_rejected(self):
        self.authenticate(self.accountant_one)

        url = reverse("student_invoice-list")

        payload = {
            "student": self.student_one.pk,
            "academic_term": self.term_one.pk,
            "invoice_number": "INV-NEGATIVE-DISCOUNT",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "discount_amount": "-1000.00",
            "adjustment_amount": "0.00",
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
            "discount_amount",
            response.data,
        )

    # -----------------------------------------------------------------
    # Issue workflow
    # -----------------------------------------------------------------

    def test_invoice_without_items_cannot_be_issued(self):
        self.authenticate(self.accountant_one)

        url = reverse(
            "student_invoice-issue",
            args=[self.invoice_one.pk],
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

        self.invoice_one.refresh_from_db()

        self.assertEqual(
            self.invoice_one.status,
            StudentInvoice.Status.DRAFT,
        )

    def test_invoice_with_item_can_be_issued(self):
        create_invoice_item(
            invoice=self.invoice_one,
            fee_structure=self.fee_structure_one,
        )

        self.authenticate(self.accountant_one)

        url = reverse(
            "student_invoice-issue",
            args=[self.invoice_one.pk],
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

        self.invoice_one.refresh_from_db()

        self.assertEqual(
            self.invoice_one.status,
            StudentInvoice.Status.ISSUED,
        )
        self.assertEqual(
            self.invoice_one.subtotal,
            Decimal("100000.00"),
        )
        self.assertEqual(
            self.invoice_one.total_amount,
            Decimal("100000.00"),
        )

        # This confirms refresh_from_db() is working in the ViewSet.
        self.assertEqual(
            response.data["status"],
            StudentInvoice.Status.ISSUED,
        )
        self.assertEqual(
            Decimal(response.data["total_amount"]),
            Decimal("100000.00"),
        )

    def test_issuing_invoice_creates_financial_transaction(self):
        create_invoice_item(
            invoice=self.invoice_one,
            fee_structure=self.fee_structure_one,
        )

        self.authenticate(self.admin_one)

        url = reverse(
            "student_invoice-issue",
            args=[self.invoice_one.pk],
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

        transaction = FinancialTransaction.objects.get(
            invoice=self.invoice_one,
            transaction_type=(
                FinancialTransaction.TransactionType.INVOICE_ISSUED
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
            Decimal("100000.00"),
        )
        self.assertEqual(
            transaction.created_by,
            self.admin_one,
        )

    def test_invoice_cannot_be_issued_twice(self):
        create_invoice_item(
            invoice=self.invoice_one,
            fee_structure=self.fee_structure_one,
        )

        self.authenticate(self.accountant_one)

        url = reverse(
            "student_invoice-issue",
            args=[self.invoice_one.pk],
        )

        first_response = self.client.post(
            url,
            {},
            format="json",
        )

        second_response = self.client.post(
            url,
            {},
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    # -----------------------------------------------------------------
    # Cancellation workflow
    # -----------------------------------------------------------------

    def test_invoice_can_be_cancelled(self):
        create_invoice_item(
            invoice=self.invoice_one,
            fee_structure=self.fee_structure_one,
        )

        self.authenticate(self.accountant_one)

        issue_url = reverse(
            "student_invoice-issue",
            args=[self.invoice_one.pk],
        )

        issue_response = self.client.post(
            issue_url,
            {},
            format="json",
        )

        self.assertEqual(
            issue_response.status_code,
            status.HTTP_200_OK,
            issue_response.data,
        )

        cancel_url = reverse(
            "student_invoice-cancel",
            args=[self.invoice_one.pk],
        )

        cancel_response = self.client.post(
            cancel_url,
            {
                "reason": "Invoice created in error.",
            },
            format="json",
        )

        self.assertEqual(
            cancel_response.status_code,
            status.HTTP_200_OK,
            cancel_response.data,
        )

        self.invoice_one.refresh_from_db()

        self.assertEqual(
            self.invoice_one.status,
            StudentInvoice.Status.CANCELLED,
        )

        # This also checks the refresh_from_db() correction.
        self.assertEqual(
            cancel_response.data["status"],
            StudentInvoice.Status.CANCELLED,
        )

    def test_cancelling_invoice_creates_financial_transaction(self):
        create_invoice_item(
            invoice=self.invoice_one,
            fee_structure=self.fee_structure_one,
        )

        self.authenticate(self.admin_one)

        issue_url = reverse(
            "student_invoice-issue",
            args=[self.invoice_one.pk],
        )

        self.client.post(
            issue_url,
            {},
            format="json",
        )

        cancel_url = reverse(
            "student_invoice-cancel",
            args=[self.invoice_one.pk],
        )

        response = self.client.post(
            cancel_url,
            {
                "reason": "Duplicate invoice.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        transaction = FinancialTransaction.objects.get(
            invoice=self.invoice_one,
            transaction_type=(
                FinancialTransaction.TransactionType.INVOICE_CANCELLED
            ),
        )

        self.assertEqual(
            transaction.amount,
            Decimal("100000.00"),
        )
        self.assertEqual(
            transaction.created_by,
            self.admin_one,
        )
        self.assertEqual(
            transaction.description,
            "Duplicate invoice.",
        )

    # -----------------------------------------------------------------
    # School isolation on actions
    # -----------------------------------------------------------------

    def test_accountant_cannot_issue_another_schools_invoice(self):
        foreign_invoice = create_invoice(
            school=self.school_two,
            student=self.student_two,
            term=self.term_two,
            created_by=self.admin_two,
        )

        self.authenticate(self.accountant_one)

        url = reverse(
            "student_invoice-issue",
            args=[foreign_invoice.pk],
        )

        response = self.client.post(
            url,
            {},
            format="json",
        )

        # The foreign invoice is hidden by the scoped queryset.
        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )