# finance/serializers.py

from decimal import Decimal

from rest_framework import serializers

from .models import (
    Expense,
    ExpenseCategory,
    FeeCategory,
    FeeStructure,
    InvoiceItem,
    Payment,
    PaymentAllocation,
    Receipt,
    StudentInvoice,
)

ZERO = Decimal("0.00")


class SchoolIsolationMixin:
    """Makes the school field read-only for non-superusers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        user = getattr(request, "user", None)

        if (
            user
            and user.is_authenticated
            and not user.is_superuser
            and "school" in self.fields
        ):
            self.fields["school"].read_only = True

    def get_request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_effective_school(self, attrs):
        user = self.get_request_user()

        school = attrs.get("school", getattr(self.instance, "school", None))

        if (
            school is None
            and user
            and user.is_authenticated
            and not user.is_superuser
        ):
            school = user.school

        return school


class FeeCategorySerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    class Meta:
        model = FeeCategory
        fields = [
            "id",
            "school",
            "name",
            "code",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ExpenseCategorySerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = [
            "id",
            "school",
            "name",
            "code",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class FeeStructureSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    class Meta:
        model = FeeStructure
        fields = [
            "id",
            "school",
            "academic_term",
            "classroom",
            "fee_category",
            "name",
            "amount",
            "due_date",
            "is_mandatory",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_amount(self, value):
        if value < ZERO:
            raise serializers.ValidationError("Amount must not be negative.")
        return value

    def validate(self, attrs):
        school = self.get_effective_school(attrs)

        academic_term = attrs.get(
            "academic_term", getattr(self.instance, "academic_term", None)
        )
        classroom = attrs.get(
            "classroom", getattr(self.instance, "classroom", None)
        )
        fee_category = attrs.get(
            "fee_category", getattr(self.instance, "fee_category", None)
        )

        errors = {}

        if academic_term and school and academic_term.school_id != school.id:
            errors["academic_term"] = "The academic term must belong to the same school."

        if classroom and school and classroom.school_id != school.id:
            errors["classroom"] = "The classroom must belong to the same school."

        if fee_category and school and fee_category.school_id != school.id:
            errors["fee_category"] = "The fee category must belong to the same school."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = [
            "id",
            "invoice",
            "fee_structure",
            "fee_category",
            "description",
            "quantity",
            "unit_amount",
            "discount_amount",
            "total_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "total_amount", "created_at", "updated_at"]

    def validate_unit_amount(self, value):
        if value < ZERO:
            raise serializers.ValidationError("Unit amount must not be negative.")
        return value

    def validate_discount_amount(self, value):
        if value < ZERO:
            raise serializers.ValidationError("Discount amount must not be negative.")
        return value

    def validate(self, attrs):
        invoice = attrs.get("invoice", getattr(self.instance, "invoice", None))

        if invoice and invoice.status in (
            StudentInvoice.Status.PAID,
            StudentInvoice.Status.CANCELLED,
        ):
            raise serializers.ValidationError(
                "Items cannot be modified on a paid or cancelled invoice."
            )

        fee_structure = attrs.get(
            "fee_structure", getattr(self.instance, "fee_structure", None)
        )
        fee_category = attrs.get(
            "fee_category", getattr(self.instance, "fee_category", None)
        )

        errors = {}

        if invoice and fee_structure and fee_structure.school_id != invoice.school_id:
            errors["fee_structure"] = "The fee structure must belong to the same school as the invoice."

        if invoice and fee_category and fee_category.school_id != invoice.school_id:
            errors["fee_category"] = "The fee category must belong to the same school as the invoice."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class StudentInvoiceSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = StudentInvoice
        fields = [
            "id",
            "school",
            "student",
            "student_name",
            "academic_term",
            "invoice_number",
            "issue_date",
            "due_date",
            "status",
            "subtotal",
            "discount_amount",
            "adjustment_amount",
            "total_amount",
            "amount_paid",
            "balance",
            "notes",
            "items",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "subtotal",
            "total_amount",
            "amount_paid",
            "balance",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_student_name(self, obj):
        user = obj.student.user
        return user.get_full_name() if hasattr(user, "get_full_name") else str(user)

    def validate_discount_amount(self, value):
        if value < ZERO:
            raise serializers.ValidationError("Discount amount must not be negative.")
        return value

    def validate(self, attrs):
        school = self.get_effective_school(attrs)

        student = attrs.get("student", getattr(self.instance, "student", None))
        academic_term = attrs.get(
            "academic_term", getattr(self.instance, "academic_term", None)
        )
        invoice_number = attrs.get(
            "invoice_number", getattr(self.instance, "invoice_number", None)
        )

        errors = {}

        if student and school and student.school_id != school.id:
            errors["student"] = "The student must belong to the same school."

        if academic_term and school and academic_term.school_id != school.id:
            errors["academic_term"] = "The academic term must belong to the same school."

        if invoice_number and school:
            duplicate_qs = StudentInvoice.objects.filter(
                school=school, invoice_number=invoice_number
            )
            if self.instance:
                duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
            if duplicate_qs.exists():
                errors["invoice_number"] = "This invoice number is already in use for this school."

        if self.instance and self.instance.status in (
            StudentInvoice.Status.PAID,
            StudentInvoice.Status.CANCELLED,
        ):
            immutable_fields = {"student", "academic_term", "invoice_number"}
            if immutable_fields & set(attrs.keys()):
                errors["status"] = "Paid or cancelled invoices cannot be modified."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class PaymentSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    unallocated_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Payment
        fields = [
            "id",
            "school",
            "student",
            "payment_reference",
            "payment_date",
            "amount",
            "payment_method",
            "status",
            "external_reference",
            "notes",
            "received_by",
            "unallocated_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "received_by",
            "created_at",
            "updated_at",
        ]

    def validate_amount(self, value):
        if value < ZERO:
            raise serializers.ValidationError("Amount must not be negative.")
        return value

    def validate(self, attrs):
        school = self.get_effective_school(attrs)

        student = attrs.get("student", getattr(self.instance, "student", None))
        payment_reference = attrs.get(
            "payment_reference", getattr(self.instance, "payment_reference", None)
        )

        errors = {}

        if student and school and student.school_id != school.id:
            errors["student"] = "The student must belong to the same school."

        if payment_reference and school:
            duplicate_qs = Payment.objects.filter(
                school=school, payment_reference=payment_reference
            )
            if self.instance:
                duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
            if duplicate_qs.exists():
                errors["payment_reference"] = "This payment reference is already in use for this school."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class PaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAllocation
        fields = [
            "id",
            "payment",
            "invoice",
            "amount",
            "allocated_by",
            "allocated_at",
        ]
        read_only_fields = ["id", "allocated_by", "allocated_at"]

    def validate_amount(self, value):
        if value <= ZERO:
            raise serializers.ValidationError("Allocation amount must be greater than zero.")
        return value

    def validate(self, attrs):
        payment = attrs.get("payment", getattr(self.instance, "payment", None))
        invoice = attrs.get("invoice", getattr(self.instance, "invoice", None))

        errors = {}

        if payment and invoice:
            if payment.school_id != invoice.school_id:
                errors["invoice"] = "The payment and invoice must belong to the same school."
            if payment.student_id != invoice.student_id:
                errors["invoice"] = "The payment and invoice must belong to the same student."

        if payment and payment.status != Payment.Status.COMPLETED:
            errors["payment"] = "Only completed payments can be allocated."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class ReceiptSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = [
            "id",
            "school",
            "payment",
            "receipt_number",
            "issued_at",
            "issued_by",
            "notes",
        ]
        read_only_fields = ["id", "issued_at", "issued_by"]

    def validate(self, attrs):
        school = self.get_effective_school(attrs)
        payment = attrs.get("payment", getattr(self.instance, "payment", None))
        receipt_number = attrs.get(
            "receipt_number", getattr(self.instance, "receipt_number", None)
        )

        errors = {}

        if payment and school and payment.school_id != school.id:
            errors["payment"] = "The payment must belong to the same school."

        if receipt_number and school:
            duplicate_qs = Receipt.objects.filter(
                school=school, receipt_number=receipt_number
            )
            if self.instance:
                duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
            if duplicate_qs.exists():
                errors["receipt_number"] = "This receipt number is already in use for this school."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class ExpenseSerializer(SchoolIsolationMixin, serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = [
            "id",
            "school",
            "category",
            "description",
            "amount",
            "expense_date",
            "payment_method",
            "reference",
            "status",
            "recorded_by",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "recorded_by",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def validate_amount(self, value):
        if value < ZERO:
            raise serializers.ValidationError("Amount must not be negative.")
        return value

    def validate(self, attrs):
        school = self.get_effective_school(attrs)
        category = attrs.get("category", getattr(self.instance, "category", None))

        errors = {}

        if category and school and category.school_id != school.id:
            errors["category"] = "The category must belong to the same school."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs