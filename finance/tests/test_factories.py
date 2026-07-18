from django.test import TestCase

from finance.models import (
    Expense,
    ExpenseCategory,
    FeeCategory,
    FeeStructure,
    InvoiceItem,
    Payment,
    StudentInvoice,
)

from .factories import (
    create_accountant,
    create_academic_term,
    create_academic_year,
    create_classroom,
    create_expense,
    create_expense_category,
    create_fee_category,
    create_fee_structure,
    create_invoice,
    create_invoice_item,
    create_payment,
    create_school,
    create_student,
)


class FinanceFactoriesTests(TestCase):
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

    def test_school_and_users_are_created(self):
        self.assertEqual(self.school.name, "Test School")
        self.assertEqual(self.accountant.school, self.school)
        self.assertEqual(self.student.school, self.school)
        self.assertEqual(self.student.classroom, self.classroom)

    def test_academic_structure_is_created(self):
        self.assertEqual(self.academic_year.school, self.school)
        self.assertEqual(self.academic_term.school, self.school)
        self.assertEqual(self.academic_term.academic_year, self.academic_year)
        self.assertEqual(self.classroom.school, self.school)

    def test_fee_objects_are_created(self):
        fee_category = create_fee_category(self.school)

        fee_structure = create_fee_structure(
            self.school,
            self.academic_term,
            self.classroom,
            fee_category,
            self.accountant,
        )

        self.assertIsInstance(fee_category, FeeCategory)
        self.assertIsInstance(fee_structure, FeeStructure)
        self.assertEqual(fee_structure.school, self.school)
        self.assertEqual(fee_structure.fee_category, fee_category)

    def test_invoice_and_item_are_created(self):
        fee_category = create_fee_category(self.school)

        fee_structure = create_fee_structure(
            self.school,
            self.academic_term,
            self.classroom,
            fee_category,
            self.accountant,
        )

        invoice = create_invoice(
            self.school,
            self.student,
            self.academic_term,
            self.accountant,
        )

        item = create_invoice_item(invoice, fee_structure)

        self.assertIsInstance(invoice, StudentInvoice)
        self.assertIsInstance(item, InvoiceItem)
        self.assertEqual(item.invoice, invoice)
        self.assertEqual(item.fee_structure, fee_structure)

    def test_payment_is_created(self):
        payment = create_payment(
            self.school,
            self.student,
            self.accountant,
        )

        self.assertIsInstance(payment, Payment)
        self.assertEqual(payment.school, self.school)
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.status, Payment.Status.PENDING)

    def test_expense_objects_are_created(self):
        category = create_expense_category(self.school)

        expense = create_expense(
            self.school,
            category,
            self.accountant,
        )

        self.assertIsInstance(category, ExpenseCategory)
        self.assertIsInstance(expense, Expense)
        self.assertEqual(expense.school, self.school)
        self.assertEqual(expense.category, category)
        self.assertEqual(expense.recorded_by, self.accountant)
    
    def test_factory_objects_are_saved_to_database(self):
        fee_category = create_fee_category(self.school)
        expense_category = create_expense_category(self.school)

        self.assertTrue(
            FeeCategory.objects.filter(pk=fee_category.pk).exists()
        )
        self.assertTrue(
            ExpenseCategory.objects.filter(
                pk=expense_category.pk
            ).exists()
        )