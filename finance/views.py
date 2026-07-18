# finance/views.py

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.models import GuardianStudentLink, User

from . import services
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
from .permissions import IsFinanceManager, IsOwnStudentOrLinkedGuardianReadOnly
from .serializers import (
    ExpenseCategorySerializer,
    ExpenseSerializer,
    FeeCategorySerializer,
    FeeStructureSerializer,
    InvoiceItemSerializer,
    PaymentAllocationSerializer,
    PaymentSerializer,
    ReceiptSerializer,
    StudentInvoiceSerializer,
)


def _linked_student_profile_ids(user):
    student_user_ids = GuardianStudentLink.objects.filter(
        guardian=user,
    ).values_list("student_id", flat=True)
    return student_user_ids


class SchoolScopedFinanceViewSet(viewsets.ModelViewSet):
    """Base ViewSet enforcing school isolation for finance-manager-only models."""

    permission_classes = [IsFinanceManager]

    def get_base_queryset(self):
        raise NotImplementedError

    def get_queryset(self):
        user = self.request.user
        queryset = self.get_base_queryset()

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return queryset.none()

        return queryset.filter(school_id=user.school_id)

    def perform_create(self, serializer):
        user = self.request.user

        if user.is_superuser:
            serializer.save()
        else:
            serializer.save(school=user.school)


class FeeCategoryViewSet(SchoolScopedFinanceViewSet):
    serializer_class = FeeCategorySerializer

    def get_base_queryset(self):
        return FeeCategory.objects.select_related("school").order_by("school", "name")


class FeeStructureViewSet(SchoolScopedFinanceViewSet):
    serializer_class = FeeStructureSerializer

    def get_base_queryset(self):
        return FeeStructure.objects.select_related(
            "school", "academic_term", "classroom", "fee_category", "created_by"
        ).order_by("school", "academic_term", "name")

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(
            school=user.school if not user.is_superuser else serializer.validated_data.get("school"),
            created_by=user,
        )


class StudentInvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = StudentInvoiceSerializer

    def get_permissions(self):
        user = self.request.user

        if (
            user.is_authenticated
            and user.role in (User.Role.STUDENT, User.Role.GUARDIAN)
            and self.request.method in ("GET", "HEAD", "OPTIONS")
        ):
            return [IsOwnStudentOrLinkedGuardianReadOnly()]

        return [IsFinanceManager()]

    def get_queryset(self):
        user = self.request.user

        queryset = StudentInvoice.objects.select_related(
            "school", "student", "student__user", "academic_term", "created_by"
        ).prefetch_related("items").order_by("-issue_date", "school")

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.role in (User.Role.ADMIN, User.Role.ACCOUNTANT):
            if user.school_id is None:
                return queryset.none()
            return queryset.filter(school_id=user.school_id)

        if user.role == User.Role.STUDENT:
            try:
                student_profile = user.student_profile
            except User.student_profile.RelatedObjectDoesNotExist:
                return queryset.none()
            return queryset.filter(student=student_profile)

        if user.role == User.Role.GUARDIAN:
            linked_user_ids = _linked_student_profile_ids(user)
            return queryset.filter(student__user_id__in=linked_user_ids)

        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(
            school=user.school if not user.is_superuser else serializer.validated_data.get("school"),
            created_by=user,
        )

    def perform_destroy(self, instance):
        if instance.status == StudentInvoice.Status.PAID:
            raise PermissionDenied("Paid invoices cannot be deleted.")
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"], url_path="issue")
    def issue(self, request, pk=None):
        invoice = self.get_object()

        try:
            services.issue_invoice(invoice, request.user)
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        invoice.refresh_from_db()

        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        invoice = self.get_object()

        try:
            services.cancel_invoice(
                invoice,
                request.user,
                reason=request.data.get("reason", ""),
            )
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        invoice.refresh_from_db()

        return Response(self.get_serializer(invoice).data)

    @action(detail=False, methods=["get"], url_path="unpaid")
    def unpaid(self, request):
        queryset = self.filter_queryset(self.get_queryset()).exclude(
            status__in=[StudentInvoice.Status.PAID, StudentInvoice.Status.CANCELLED]
        )
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class InvoiceItemViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceItemSerializer
    permission_classes = [IsFinanceManager]

    def get_queryset(self):
        user = self.request.user

        queryset = InvoiceItem.objects.select_related(
            "invoice", "invoice__school", "fee_structure", "fee_category"
        ).order_by("invoice", "id")

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return queryset.none()

        return queryset.filter(invoice__school_id=user.school_id)

    def perform_create(self, serializer):
        instance = serializer.save()
        services.recalculate_invoice_totals(instance.invoice)

    def perform_update(self, serializer):
        instance = serializer.save()
        services.recalculate_invoice_totals(instance.invoice)

    def perform_destroy(self, instance):
        invoice = instance.invoice
        if invoice.status in (StudentInvoice.Status.PAID, StudentInvoice.Status.CANCELLED):
            raise PermissionDenied("Items cannot be removed from a paid or cancelled invoice.")
        instance.delete()
        services.recalculate_invoice_totals(invoice)


class PaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentSerializer

    def get_permissions(self):
        user = self.request.user

        if (
            user.is_authenticated
            and user.role in (User.Role.STUDENT, User.Role.GUARDIAN)
            and self.request.method in ("GET", "HEAD", "OPTIONS")
        ):
            return [IsOwnStudentOrLinkedGuardianReadOnly()]

        return [IsFinanceManager()]

    def get_queryset(self):
        user = self.request.user

        queryset = Payment.objects.select_related(
            "school", "student", "student__user", "received_by"
        ).prefetch_related("allocations").order_by("-payment_date", "school")

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.role in (User.Role.ADMIN, User.Role.ACCOUNTANT):
            if user.school_id is None:
                return queryset.none()
            return queryset.filter(school_id=user.school_id)

        if user.role == User.Role.STUDENT:
            try:
                student_profile = user.student_profile
            except User.student_profile.RelatedObjectDoesNotExist:
                return queryset.none()
            return queryset.filter(student=student_profile)

        if user.role == User.Role.GUARDIAN:
            linked_user_ids = _linked_student_profile_ids(user)
            return queryset.filter(student__user_id__in=linked_user_ids)

        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(
            school=user.school if not user.is_superuser else serializer.validated_data.get("school"),
            received_by=user,
        )

    def perform_destroy(self, instance):
        raise PermissionDenied(
            "Payments cannot be deleted; cancel or reverse them instead."
        )

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        payment = self.get_object()

        try:
            services.record_payment(payment, request.user)
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        payment.refresh_from_db()

        return Response(self.get_serializer(payment).data)

    @action(detail=True, methods=["post"], url_path="allocate")
    def allocate(self, request, pk=None):
        payment = self.get_object()

        invoice_id = request.data.get("invoice")
        raw_amount = request.data.get("amount")

        if not invoice_id or raw_amount is None:
            raise ValidationError({"detail": "invoice and amount are required."})

        try:
            amount = Decimal(str(raw_amount))
        except (InvalidOperation, ValueError):
            raise ValidationError({"amount": "Enter a valid decimal amount."})

        try:
            invoice = StudentInvoice.objects.get(pk=invoice_id)
        except StudentInvoice.DoesNotExist:
            raise ValidationError({"invoice": "Invoice not found."})

        user = request.user
        if not user.is_superuser and invoice.school_id != user.school_id:
            raise PermissionDenied("You may only allocate payments within your own school.")

        try:
            allocation = services.allocate_payment(payment, invoice, amount, user)
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        return Response(
            PaymentAllocationSerializer(allocation).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="reverse")
    def reverse(self, request, pk=None):
        payment = self.get_object()

        try:
            services.reverse_payment(
                payment,
                request.user,
                reason=request.data.get("reason", ""),
            )
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        payment.refresh_from_db()

        return Response(self.get_serializer(payment).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        payment = self.get_object()

        try:
            services.cancel_payment(
                payment,
                request.user,
                reason=request.data.get("reason", ""),
            )
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        payment.refresh_from_db()

        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["get"], url_path="history")
    def history(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        student_id = request.query_params.get("student")
        if student_id:
            queryset = queryset.filter(student_id=student_id)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class PaymentAllocationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentAllocationSerializer
    permission_classes = [IsFinanceManager]

    def get_queryset(self):
        user = self.request.user

        queryset = PaymentAllocation.objects.select_related(
            "payment", "invoice", "allocated_by"
        ).order_by("-allocated_at")

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.school_id is None:
            return queryset.none()

        return queryset.filter(payment__school_id=user.school_id)


class ReceiptViewSet(viewsets.ModelViewSet):
    serializer_class = ReceiptSerializer

    def get_permissions(self):
        user = self.request.user

        if (
            user.is_authenticated
            and user.role in (User.Role.STUDENT, User.Role.GUARDIAN)
            and self.request.method in ("GET", "HEAD", "OPTIONS")
        ):
            return [IsOwnStudentOrLinkedGuardianReadOnly()]

        return [IsFinanceManager()]

    def get_queryset(self):
        user = self.request.user

        queryset = Receipt.objects.select_related(
            "school", "payment", "payment__student", "payment__student__user", "issued_by"
        ).order_by("-issued_at")

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.role in (User.Role.ADMIN, User.Role.ACCOUNTANT):
            if user.school_id is None:
                return queryset.none()
            return queryset.filter(school_id=user.school_id)

        if user.role == User.Role.STUDENT:
            try:
                student_profile = user.student_profile
            except User.student_profile.RelatedObjectDoesNotExist:
                return queryset.none()
            return queryset.filter(payment__student=student_profile)

        if user.role == User.Role.GUARDIAN:
            linked_user_ids = _linked_student_profile_ids(user)
            return queryset.filter(payment__student__user_id__in=linked_user_ids)

        return queryset.none()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = serializer.validated_data["payment"]
        receipt_number = serializer.validated_data["receipt_number"]
        notes = serializer.validated_data.get("notes", "")

        try:
            receipt = services.generate_receipt(
                payment=payment,
                user=request.user,
                receipt_number=receipt_number,
            )
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        if notes:
            receipt.notes = notes
            receipt.save(update_fields=["notes"])

        output_serializer = self.get_serializer(receipt)

        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    def perform_destroy(self, instance):
        raise PermissionDenied("Receipts cannot be deleted.")


class ExpenseCategoryViewSet(SchoolScopedFinanceViewSet):
    serializer_class = ExpenseCategorySerializer

    def get_base_queryset(self):
        return ExpenseCategory.objects.select_related("school").order_by("school", "name")


class ExpenseViewSet(SchoolScopedFinanceViewSet):
    serializer_class = ExpenseSerializer

    def get_base_queryset(self):
        return Expense.objects.select_related(
            "school",
            "category",
            "recorded_by",
            "approved_by",
        ).order_by("-expense_date", "school")

    def perform_create(self, serializer):
        user = self.request.user

        serializer.save(
            school=(
                user.school
                if not user.is_superuser
                else serializer.validated_data.get("school")
            ),
            recorded_by=user,
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        expense = self.get_object()

        try:
            services.submit_expense(expense, request.user)
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        expense.refresh_from_db()
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        expense = self.get_object()

        try:
            services.approve_expense(expense, request.user)
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        expense.refresh_from_db()
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        expense = self.get_object()

        try:
            services.reject_expense(
                expense,
                request.user,
                reason=request.data.get("reason", ""),
            )
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        expense.refresh_from_db()
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        expense = self.get_object()

        try:
            services.mark_expense_paid(expense, request.user)
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        expense.refresh_from_db()
        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        expense = self.get_object()

        try:
            services.cancel_expense(
                expense,
                request.user,
                reason=request.data.get("reason", ""),
            )
        except services.FinanceServiceError as exc:
            raise ValidationError(str(exc))

        expense.refresh_from_db()
        return Response(self.get_serializer(expense).data)