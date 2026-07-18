from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from finance.models import FeeCategory

from .factories import (
    create_academic_term,
    create_academic_year,
    create_accountant,
    create_admin,
    create_classroom,
    create_fee_category,
    create_invoice,
    create_school,
    create_student,
)


class FinanceAPISecurityTests(APITestCase):
    """
    Tests authentication, role permissions and school isolation for
    Finance API endpoints.
    """

    def setUp(self):
        # -------------------------------------------------------------
        # School one
        # -------------------------------------------------------------
        self.school_one = create_school(
            name="School One",
            code="SCH-ONE",
        )

        self.admin_one = create_admin(
            school=self.school_one,
            email="admin.one@test.com",
        )

        self.accountant_one = create_accountant(
            school=self.school_one,
            email="accountant.one@test.com",
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
            email="student.one@test.com",
            student_id_number="STU-ONE",
        )

        self.invoice_one = create_invoice(
            school=self.school_one,
            student=self.student_one,
            term=self.term_one,
            created_by=self.admin_one,
        )

        self.fee_category_one = create_fee_category(self.school_one)

        # -------------------------------------------------------------
        # School two
        # -------------------------------------------------------------
        self.school_two = create_school(
            name="School Two",
            code="SCH-TWO",
        )

        self.admin_two = create_admin(
            school=self.school_two,
            email="admin.two@test.com",
        )

        self.accountant_two = create_accountant(
            school=self.school_two,
            email="accountant.two@test.com",
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
            email="student.two@test.com",
            student_id_number="STU-TWO",
        )

        self.invoice_two = create_invoice(
            school=self.school_two,
            student=self.student_two,
            term=self.term_two,
            created_by=self.admin_two,
        )

        self.fee_category_two = create_fee_category(self.school_two)

    def authenticate(self, user):
        """Authenticate the API client as the supplied user."""
        self.client.force_authenticate(user=user)

    @staticmethod
    def response_results(response):
        """
        Return list data whether pagination is enabled or disabled.
        """
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]

        return response.data

    # -----------------------------------------------------------------
    # Authentication
    # -----------------------------------------------------------------

    def test_unauthenticated_user_cannot_list_fee_categories(self):
        url = reverse("fee_category-list")

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_unauthenticated_user_cannot_view_invoices(self):
        url = reverse("student_invoice-list")

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    # -----------------------------------------------------------------
    # Finance manager permissions
    # -----------------------------------------------------------------

    def test_approved_admin_can_list_fee_categories(self):
        self.authenticate(self.admin_one)

        url = reverse("fee_category-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_approved_accountant_can_list_fee_categories(self):
        self.authenticate(self.accountant_one)

        url = reverse("fee_category-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_student_cannot_create_fee_category(self):
        self.authenticate(self.student_one.user)

        url = reverse("fee_category-list")

        payload = {
            "name": "Development Fee",
            "code": "DEV-FEE",
            "description": "Development contribution",
            "is_active": True,
        }

        response = self.client.post(
            url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertFalse(
            FeeCategory.objects.filter(
                school=self.school_one,
                code="DEV-FEE",
            ).exists()
        )

    def test_unapproved_accountant_cannot_access_finance_api(self):
        pending_accountant = User.objects.create_user(
            email="pending.accountant@test.com",
            password="password123",
            first_name="Pending",
            last_name="Accountant",
            role=User.Role.ACCOUNTANT,
            approval_status=User.ApprovalStatus.PENDING,
            school=self.school_one,
            is_active=True,
        )

        self.authenticate(pending_accountant)

        url = reverse("fee_category-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_inactive_accountant_cannot_access_finance_api(self):
        inactive_accountant = User.objects.create_user(
            email="inactive.accountant@test.com",
            password="password123",
            first_name="Inactive",
            last_name="Accountant",
            role=User.Role.ACCOUNTANT,
            approval_status=User.ApprovalStatus.APPROVED,
            school=self.school_one,
            is_active=False,
        )

        self.authenticate(inactive_accountant)

        url = reverse("fee_category-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    # -----------------------------------------------------------------
    # Automatic school assignment
    # -----------------------------------------------------------------

    def test_accountant_created_fee_category_uses_accountant_school(self):
        self.authenticate(self.accountant_one)

        url = reverse("fee_category-list")

        payload = {
            "name": "Library Fee",
            "code": "LIBRARY",
            "description": "Library contribution",
            "is_active": True,

            # A non-superuser should not control the school field.
            "school": self.school_two.pk,
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

        category = FeeCategory.objects.get(
            pk=response.data["id"],
        )

        self.assertEqual(
            category.school,
            self.school_one,
        )
        self.assertEqual(
            category.name,
            "Library Fee",
        )

    # -----------------------------------------------------------------
    # School isolation
    # -----------------------------------------------------------------

    def test_admin_list_only_contains_own_school_fee_categories(self):
        self.authenticate(self.admin_one)

        url = reverse("fee_category-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = self.response_results(response)
        returned_ids = {item["id"] for item in results}

        self.assertIn(
            self.fee_category_one.pk,
            returned_ids,
        )
        self.assertNotIn(
            self.fee_category_two.pk,
            returned_ids,
        )

    def test_admin_cannot_retrieve_other_school_fee_category(self):
        self.authenticate(self.admin_one)

        url = reverse(
            "fee_category-detail",
            args=[self.fee_category_two.pk],
        )

        response = self.client.get(url)

        # The foreign object is excluded from the scoped queryset,
        # so the API should hide it with 404.
        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_admin_invoice_list_only_contains_own_school_invoices(self):
        self.authenticate(self.admin_one)

        url = reverse("student_invoice-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = self.response_results(response)
        returned_ids = {item["id"] for item in results}

        self.assertIn(
            self.invoice_one.pk,
            returned_ids,
        )
        self.assertNotIn(
            self.invoice_two.pk,
            returned_ids,
        )

    def test_admin_cannot_retrieve_other_school_invoice(self):
        self.authenticate(self.admin_one)

        url = reverse(
            "student_invoice-detail",
            args=[self.invoice_two.pk],
        )

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # -----------------------------------------------------------------
    # Student read-only access
    # -----------------------------------------------------------------

    def test_student_can_retrieve_own_invoice(self):
        self.authenticate(self.student_one.user)

        url = reverse(
            "student_invoice-detail",
            args=[self.invoice_one.pk],
        )

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["id"],
            self.invoice_one.pk,
        )
        self.assertEqual(
            response.data["student"],
            self.student_one.pk,
        )

    def test_student_cannot_retrieve_another_students_invoice(self):
        self.authenticate(self.student_one.user)

        url = reverse(
            "student_invoice-detail",
            args=[self.invoice_two.pk],
        )

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_student_invoice_list_only_contains_own_invoices(self):
        self.authenticate(self.student_one.user)

        url = reverse("student_invoice-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = self.response_results(response)
        returned_ids = {item["id"] for item in results}

        self.assertIn(
            self.invoice_one.pk,
            returned_ids,
        )
        self.assertNotIn(
            self.invoice_two.pk,
            returned_ids,
        )

    def test_student_cannot_create_invoice(self):
        self.authenticate(self.student_one.user)

        url = reverse("student_invoice-list")

        payload = {
            "student": self.student_one.pk,
            "academic_term": self.term_one.pk,
            "invoice_number": "INV-STUDENT-001",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "discount_amount": "0.00",
            "adjustment_amount": "0.00",
            "notes": "",
        }

        response = self.client.post(
            url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    # -----------------------------------------------------------------
    # Superuser access
    # -----------------------------------------------------------------

    def test_superuser_can_view_records_from_all_schools(self):
        superuser = User.objects.create_user(
    email="superuser@test.com",
    password="password123",
    first_name="System",
    last_name="Administrator",
    role=User.Role.ADMIN,
    approval_status=User.ApprovalStatus.APPROVED,
    is_active=True,
    is_staff=True,
    is_superuser=True,
)
        self.authenticate(superuser)

        url = reverse("fee_category-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        results = self.response_results(response)
        returned_ids = {item["id"] for item in results}

        self.assertIn(
            self.fee_category_one.pk,
            returned_ids,
        )
        self.assertIn(
            self.fee_category_two.pk,
            returned_ids,
        )