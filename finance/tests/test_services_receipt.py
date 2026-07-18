from django.test import TestCase

from finance.models import Payment, Receipt
from finance.services import (
    FinanceServiceError,
    generate_receipt,
    record_payment,
)

from .factories import (
    create_accountant,
    create_academic_term,
    create_academic_year,
    create_classroom,
    create_payment,
    create_school,
    create_student,
)


class ReceiptServiceTests(TestCase):
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

        self.payment = create_payment(
            self.school,
            self.student,
            self.accountant,
        )

    def complete_payment(self):
        return record_payment(
            self.payment,
            self.accountant,
        )

    def test_generate_receipt_for_completed_payment(self):
        completed_payment = self.complete_payment()

        receipt = generate_receipt(
            completed_payment,
            self.accountant,
            "REC-001",
        )

        self.assertIsInstance(receipt, Receipt)
        self.assertEqual(receipt.school, self.school)
        self.assertEqual(receipt.payment, completed_payment)
        self.assertEqual(receipt.receipt_number, "REC-001")
        self.assertEqual(receipt.issued_by, self.accountant)
        self.assertIsNotNone(receipt.issued_at)

    def test_receipt_is_saved_to_database(self):
        completed_payment = self.complete_payment()

        receipt = generate_receipt(
            completed_payment,
            self.accountant,
            "REC-001",
        )

        self.assertTrue(
            Receipt.objects.filter(pk=receipt.pk).exists()
        )

    def test_receipt_number_is_trimmed(self):
        completed_payment = self.complete_payment()

        receipt = generate_receipt(
            completed_payment,
            self.accountant,
            "   REC-001   ",
        )

        self.assertEqual(
            receipt.receipt_number,
            "REC-001",
        )

    def test_pending_payment_cannot_have_receipt(self):
        self.assertEqual(
            self.payment.status,
            Payment.Status.PENDING,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Only completed payments can have a receipt issued.",
        ):
            generate_receipt(
                self.payment,
                self.accountant,
                "REC-001",
            )

        self.assertFalse(
            Receipt.objects.filter(
                payment=self.payment,
            ).exists()
        )

    def test_blank_receipt_number_is_rejected(self):
        completed_payment = self.complete_payment()

        with self.assertRaisesMessage(
            FinanceServiceError,
            "Receipt number cannot be blank.",
        ):
            generate_receipt(
                completed_payment,
                self.accountant,
                "   ",
            )

        self.assertFalse(
            Receipt.objects.filter(
                payment=completed_payment,
            ).exists()
        )

    def test_duplicate_receipt_for_same_payment_is_rejected(self):
        completed_payment = self.complete_payment()

        generate_receipt(
            completed_payment,
            self.accountant,
            "REC-001",
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "A receipt has already been issued for this payment.",
        ):
            generate_receipt(
                completed_payment,
                self.accountant,
                "REC-002",
            )

        self.assertEqual(
            Receipt.objects.filter(
                payment=completed_payment,
            ).count(),
            1,
        )

    def test_duplicate_receipt_number_in_same_school_is_rejected(self):
        first_payment = self.complete_payment()

        generate_receipt(
            first_payment,
            self.accountant,
            "REC-001",
        )

        second_student = create_student(
            self.school,
            classroom=self.classroom,
            email="second-student@test.com",
            student_id_number="STU-002",
        )

        second_payment = create_payment(
    self.school,
    second_student,
    self.accountant,
    payment_reference="PAY-002",
)

        

        second_payment = record_payment(
            second_payment,
            self.accountant,
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "This receipt number is already in use for this school.",
        ):
            generate_receipt(
                second_payment,
                self.accountant,
                "REC-001",
            )

    def test_other_school_user_cannot_generate_receipt(self):
        completed_payment = self.complete_payment()

        other_school = create_school(
            name="Other School",
            code="OTHER",
        )

        other_accountant = create_accountant(
            other_school,
            email="other-receipt-accountant@test.com",
        )

        with self.assertRaisesMessage(
            FinanceServiceError,
            "You cannot perform this finance action for another school.",
        ):
            generate_receipt(
                completed_payment,
                other_accountant,
                "REC-001",
            )

        self.assertFalse(
            Receipt.objects.filter(
                payment=completed_payment,
            ).exists()
        )