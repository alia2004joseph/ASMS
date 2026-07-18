from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from finance.models import Receipt

from .factories import (
    create_accountant,
    create_admin,
    create_classroom,
    create_academic_year,
    create_payment,
    create_school,
    create_student,
)


class ReceiptAPITests(APITestCase):
    """
    Tests receipt generation, permissions, school isolation,
    student access and deletion protection.
    """

    def setUp(self):
        # -------------------------------------------------------------
        # School one
        # -------------------------------------------------------------
        self.school_one = create_school(
            name="Receipt School One",
            code="REC-SCH-ONE",
        )

        self.admin_one = create_admin(
            self.school_one,
            email="receipt.admin.one@test.com",
        )

        self.accountant_one = create_accountant(
            self.school_one,
            email="receipt.accountant.one@test.com",
        )

        self.year_one = create_academic_year(
            self.school_one,
        )

        self.classroom_one = create_classroom(
            self.school_one,
            self.year_one,
        )

        self.student_one = create_student(
            school=self.school_one,
            classroom=self.classroom_one,
            email="receipt.student.one@test.com",
            student_id_number="REC-STU-ONE",
        )

        # -------------------------------------------------------------
        # School two
        # -------------------------------------------------------------
        self.school_two = create_school(
            name="Receipt School Two",
            code="REC-SCH-TWO",
        )

        self.admin_two = create_admin(
            self.school_two,
            email="receipt.admin.two@test.com",
        )

        self.accountant_two = create_accountant(
            self.school_two,
            email="receipt.accountant.two@test.com",
        )

        self.year_two = create_academic_year(
            self.school_two,
        )

        self.classroom_two = create_classroom(
            self.school_two,
            self.year_two,
        )

        self.student_two = create_student(
            school=self.school_two,
            classroom=self.classroom_two,
            email="receipt.student.two@test.com",
            student_id_number="REC-STU-TWO",
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

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
        return payment

    def create_completed_payment(
        self,
        *,
        school=None,
        student=None,
        received_by=None,
        payment_reference="REC-PAY-001",
    ):
        school = school or self.school_one
        student = student or self.student_one
        received_by = received_by or self.accountant_one

        payment = create_payment(
            school=school,
            student=student,
            received_by=received_by,
            payment_reference=payment_reference,
        )

        self.complete_payment(
            payment,
            user=received_by,
        )

        return payment

    # -----------------------------------------------------------------
    # Receipt creation
    # -----------------------------------------------------------------

    def test_accountant_can_generate_receipt_for_completed_payment(self):
        payment = self.create_completed_payment(
            payment_reference="REC-PAY-CREATE",
        )

        self.authenticate(self.accountant_one)

        url = reverse("receipt-list")

        payload = {
            "payment": payment.pk,
            "receipt_number": "REC-API-001",
            "notes": "Receipt generated through the API.",
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

        receipt = Receipt.objects.get(
            receipt_number="REC-API-001",
        )

        self.assertEqual(
            receipt.school,
            self.school_one,
        )
        self.assertEqual(
            receipt.payment,
            payment,
        )
        self.assertEqual(
            receipt.issued_by,
            self.accountant_one,
        )
        self.assertEqual(
            receipt.notes,
            "Receipt generated through the API.",
        )

    def test_admin_can_generate_receipt(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.admin_one,
            payment_reference="REC-PAY-ADMIN",
        )

        self.complete_payment(
            payment,
            user=self.admin_one,
        )

        self.authenticate(self.admin_one)

        url = reverse("receipt-list")

        response = self.client.post(
            url,
            {
                "payment": payment.pk,
                "receipt_number": "REC-ADMIN-001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        receipt = Receipt.objects.get(
            receipt_number="REC-ADMIN-001",
        )

        self.assertEqual(
            receipt.issued_by,
            self.admin_one,
        )

    def test_receipt_cannot_be_generated_for_pending_payment(self):
        payment = create_payment(
            school=self.school_one,
            student=self.student_one,
            received_by=self.accountant_one,
            payment_reference="REC-PAY-PENDING",
        )

        self.authenticate(self.accountant_one)

        url = reverse("receipt-list")

        response = self.client.post(
            url,
            {
                "payment": payment.pk,
                "receipt_number": "REC-PENDING-001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            Receipt.objects.filter(
                receipt_number="REC-PENDING-001",
            ).exists()
        )

    def test_duplicate_receipt_number_is_rejected(self):
        first_payment = self.create_completed_payment(
            payment_reference="REC-PAY-DUP-ONE",
        )

        self.authenticate(self.accountant_one)

        url = reverse("receipt-list")

        first_response = self.client.post(
            url,
            {
                "payment": first_payment.pk,
                "receipt_number": "REC-DUPLICATE",
            },
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_201_CREATED,
            first_response.data,
        )

        second_payment = self.create_completed_payment(
            payment_reference="REC-PAY-DUP-TWO",
        )

        self.authenticate(self.accountant_one)

        second_response = self.client.post(
            url,
            {
                "payment": second_payment.pk,
                "receipt_number": "REC-DUPLICATE",
            },
            format="json",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            Receipt.objects.filter(
                receipt_number="REC-DUPLICATE",
            ).count(),
            1,
        )

    def test_second_receipt_cannot_be_generated_for_same_payment(self):
        payment = self.create_completed_payment(
            payment_reference="REC-PAY-SAME",
        )

        self.authenticate(self.accountant_one)

        url = reverse("receipt-list")

        first_response = self.client.post(
            url,
            {
                "payment": payment.pk,
                "receipt_number": "REC-SAME-ONE",
            },
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_201_CREATED,
            first_response.data,
        )

        second_response = self.client.post(
            url,
            {
                "payment": payment.pk,
                "receipt_number": "REC-SAME-TWO",
            },
            format="json",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            Receipt.objects.filter(
                payment=payment,
            ).count(),
            1,
        )

    # -----------------------------------------------------------------
    # School isolation
    # -----------------------------------------------------------------

    def test_accountant_cannot_generate_receipt_for_another_school_payment(
        self,
    ):
        foreign_payment = create_payment(
            school=self.school_two,
            student=self.student_two,
            received_by=self.accountant_two,
            payment_reference="REC-PAY-FOREIGN",
        )

        self.complete_payment(
            foreign_payment,
            user=self.accountant_two,
        )

        self.authenticate(self.accountant_one)

        url = reverse("receipt-list")

        response = self.client.post(
            url,
            {
                "payment": foreign_payment.pk,
                "receipt_number": "REC-FOREIGN-001",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            (
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_403_FORBIDDEN,
            ),
        )

        self.assertFalse(
            Receipt.objects.filter(
                receipt_number="REC-FOREIGN-001",
            ).exists()
        )

    def test_accountant_only_sees_receipts_from_own_school(self):
        own_payment = self.create_completed_payment(
            payment_reference="REC-PAY-LIST-ONE",
        )

        self.authenticate(self.accountant_one)

        url = reverse("receipt-list")

        own_response = self.client.post(
            url,
            {
                "payment": own_payment.pk,
                "receipt_number": "REC-LIST-ONE",
            },
            format="json",
        )

        self.assertEqual(
            own_response.status_code,
            status.HTTP_201_CREATED,
            own_response.data,
        )

        foreign_payment = create_payment(
            school=self.school_two,
            student=self.student_two,
            received_by=self.accountant_two,
            payment_reference="REC-PAY-LIST-TWO",
        )

        self.complete_payment(
            foreign_payment,
            user=self.accountant_two,
        )

        self.authenticate(self.accountant_two)

        foreign_response = self.client.post(
            url,
            {
                "payment": foreign_payment.pk,
                "receipt_number": "REC-LIST-TWO",
            },
            format="json",
        )

        self.assertEqual(
            foreign_response.status_code,
            status.HTTP_201_CREATED,
            foreign_response.data,
        )

        self.authenticate(self.accountant_one)

        list_response = self.client.get(url)

        self.assertEqual(
            list_response.status_code,
            status.HTTP_200_OK,
            list_response.data,
        )

        results = (
            list_response.data["results"]
            if isinstance(list_response.data, dict)
            and "results" in list_response.data
            else list_response.data
        )

        returned_numbers = {
            item["receipt_number"]
            for item in results
        }

        self.assertIn(
            "REC-LIST-ONE",
            returned_numbers,
        )
        self.assertNotIn(
            "REC-LIST-TWO",
            returned_numbers,
        )

    def test_accountant_cannot_retrieve_foreign_receipt(self):
        foreign_payment = create_payment(
            school=self.school_two,
            student=self.student_two,
            received_by=self.accountant_two,
            payment_reference="REC-PAY-DETAIL-FOREIGN",
        )

        self.complete_payment(
            foreign_payment,
            user=self.accountant_two,
        )

        self.authenticate(self.accountant_two)

        create_response = self.client.post(
            reverse("receipt-list"),
            {
                "payment": foreign_payment.pk,
                "receipt_number": "REC-DETAIL-FOREIGN",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            create_response.data,
        )

        receipt = Receipt.objects.get(
            receipt_number="REC-DETAIL-FOREIGN",
        )

        self.authenticate(self.accountant_one)

        detail_url = reverse(
            "receipt-detail",
            args=[receipt.pk],
        )

        response = self.client.get(detail_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # -----------------------------------------------------------------
    # Student access
    # -----------------------------------------------------------------

    def test_student_can_view_own_receipt(self):
        payment = self.create_completed_payment(
            payment_reference="REC-PAY-STUDENT-VIEW",
        )

        self.authenticate(self.accountant_one)

        create_response = self.client.post(
            reverse("receipt-list"),
            {
                "payment": payment.pk,
                "receipt_number": "REC-STUDENT-VIEW",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            create_response.data,
        )

        receipt = Receipt.objects.get(
            receipt_number="REC-STUDENT-VIEW",
        )

        self.authenticate(self.student_one.user)

        detail_url = reverse(
            "receipt-detail",
            args=[receipt.pk],
        )

        response = self.client.get(detail_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["id"],
            receipt.pk,
        )

    def test_student_cannot_view_another_students_receipt(self):
        foreign_payment = create_payment(
            school=self.school_two,
            student=self.student_two,
            received_by=self.accountant_two,
            payment_reference="REC-PAY-OTHER-STUDENT",
        )

        self.complete_payment(
            foreign_payment,
            user=self.accountant_two,
        )

        self.authenticate(self.accountant_two)

        create_response = self.client.post(
            reverse("receipt-list"),
            {
                "payment": foreign_payment.pk,
                "receipt_number": "REC-OTHER-STUDENT",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            create_response.data,
        )

        receipt = Receipt.objects.get(
            receipt_number="REC-OTHER-STUDENT",
        )

        self.authenticate(self.student_one.user)

        detail_url = reverse(
            "receipt-detail",
            args=[receipt.pk],
        )

        response = self.client.get(detail_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_student_cannot_create_receipt(self):
        payment = self.create_completed_payment(
            payment_reference="REC-PAY-STUDENT-CREATE",
        )

        self.authenticate(self.student_one.user)

        response = self.client.post(
            reverse("receipt-list"),
            {
                "payment": payment.pk,
                "receipt_number": "REC-STUDENT-CREATE",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertFalse(
            Receipt.objects.filter(
                receipt_number="REC-STUDENT-CREATE",
            ).exists()
        )

    # -----------------------------------------------------------------
    # Deletion protection
    # -----------------------------------------------------------------

    def test_receipt_cannot_be_deleted(self):
        payment = self.create_completed_payment(
            payment_reference="REC-PAY-NO-DELETE",
        )

        self.authenticate(self.accountant_one)

        create_response = self.client.post(
            reverse("receipt-list"),
            {
                "payment": payment.pk,
                "receipt_number": "REC-NO-DELETE",
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            create_response.data,
        )

        receipt = Receipt.objects.get(
            receipt_number="REC-NO-DELETE",
        )

        detail_url = reverse(
            "receipt-detail",
            args=[receipt.pk],
        )

        delete_response = self.client.delete(detail_url)

        self.assertEqual(
            delete_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertTrue(
            Receipt.objects.filter(
                pk=receipt.pk,
            ).exists()
        )