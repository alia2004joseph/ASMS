"""
Reusable test data builders for the Finance app.

These are intentionally simple helper functions rather than full factory
libraries. They keep the test suite readable while avoiding additional
dependencies such as factory_boy.
"""

from decimal import Decimal

from django.utils import timezone

from accounts.models import User, StudentProfile
from academics.models import (
    AcademicTerm,
    AcademicYear,
    Classroom,
)
from schools.models import School
from finance.models import (
    Expense,
    ExpenseCategory,
    FeeCategory,
    FeeStructure,
    InvoiceItem,
    Payment,
    StudentInvoice,
)


def create_school(name="Test School", code="TS"):
    return School.objects.create(
        name=name,
        code=code,
    )


def create_admin(school, email="admin@test.com"):
    return User.objects.create_user(
        email=email,
        password="password123",
        first_name="Finance",
        last_name="Admin",
        role=User.Role.ADMIN,
        approval_status=User.ApprovalStatus.APPROVED,
        school=school,
        is_active=True,
    )


def create_accountant(school, email="accountant@test.com"):
    return User.objects.create_user(
        email=email,
        password="password123",
        first_name="Finance",
        last_name="Accountant",
        role=User.Role.ACCOUNTANT,
        approval_status=User.ApprovalStatus.APPROVED,
        school=school,
        is_active=True,
    )


def create_student(
    school,
    classroom=None,
    email="student@test.com",
    student_id_number="STU-001",
):
    user = User.objects.create_user(
        email=email,
        password="password123",
        first_name="John",
        last_name="Student",
        role=User.Role.STUDENT,
        approval_status=User.ApprovalStatus.APPROVED,
        school=school,
        is_active=True,
    )

    return StudentProfile.objects.create(
        user=user,
        school=school,
        classroom=classroom,
        student_id_number=student_id_number,
        is_active_student=True,
    )


def create_academic_year(school):
    return AcademicYear.objects.create(
        school=school,
        name="2026",
        start_date=timezone.datetime(2026, 1, 1).date(),
        end_date=timezone.datetime(2026, 12, 31).date(),
    )


def create_academic_term(school, academic_year):
    return AcademicTerm.objects.create(
        school=school,
        academic_year=academic_year,
        name="term_one",
        start_date=timezone.datetime(2026, 1, 1).date(),
        end_date=timezone.datetime(2026, 4, 30).date(),
    )


def create_classroom(school, academic_year):
    return Classroom.objects.create(
        school=school,
        academic_year=academic_year,
        name="Senior One",
        code="S1",
        level="S1",
    )


def create_fee_category(school):
    return FeeCategory.objects.create(
        school=school,
        name="Tuition",
        code="TUITION",
    )


def create_fee_structure(school, term, classroom, fee_category, created_by):
    return FeeStructure.objects.create(
        school=school,
        academic_term=term,
        classroom=classroom,
        fee_category=fee_category,
        name="School Fees",
        amount=Decimal("100000.00"),
        due_date=term.end_date,
        created_by=created_by,
    )


def create_invoice(school, student, term, created_by):
    return StudentInvoice.objects.create(
        school=school,
        student=student,
        academic_term=term,
        invoice_number="INV-001",
        issue_date=timezone.localdate(),
        due_date=timezone.localdate(),
        status=StudentInvoice.Status.DRAFT,
        created_by=created_by,
    )


def create_invoice_item(invoice, fee_structure):
    return InvoiceItem.objects.create(
        invoice=invoice,
        fee_structure=fee_structure,
        fee_category=fee_structure.fee_category,
        description="Tuition",
        quantity=1,
        unit_amount=Decimal("100000.00"),
        discount_amount=Decimal("0.00"),
    )


def create_payment(
    school,
    student,
    received_by,
    payment_reference="PAY-001",
    payment_method="cash",
    amount=Decimal("100000.00"),
):
    return Payment.objects.create(
        school=school,
        student=student,
        payment_reference=payment_reference,
        payment_date=timezone.localdate(),
        amount=amount,
        payment_method=payment_method,
        received_by=received_by,
        status=Payment.Status.PENDING,
    )

def create_expense_category(school):
    return ExpenseCategory.objects.create(
        school=school,
        name="Utilities",
        code="UTIL",
    )


def create_expense(
    school,
    category,
    recorded_by,
    payment_method="cash",
):
    return Expense.objects.create(
        school=school,
        category=category,
        description="Electricity",
        amount=Decimal("25000.00"),
        expense_date=timezone.localdate(),
        payment_method=payment_method,
        status=Expense.Status.DRAFT,
        recorded_by=recorded_by,
    )