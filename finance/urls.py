# finance/urls.py

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    FeeCategoryViewSet,
    FeeStructureViewSet,
    InvoiceItemViewSet,
    PaymentAllocationViewSet,
    PaymentViewSet,
    ReceiptViewSet,
    StudentInvoiceViewSet,
)

router = DefaultRouter()
router.register(r"fee-categories", FeeCategoryViewSet, basename="fee_category")
router.register(r"expense-categories", ExpenseCategoryViewSet, basename="expense_category")
router.register(r"fee-structures", FeeStructureViewSet, basename="fee_structure")
router.register(r"invoices", StudentInvoiceViewSet, basename="student_invoice")
router.register(r"invoice-items", InvoiceItemViewSet, basename="invoice_item")
router.register(r"payments", PaymentViewSet, basename="payment")
router.register(
    r"payment-allocations", PaymentAllocationViewSet, basename="payment_allocation"
)
router.register(r"receipts", ReceiptViewSet, basename="receipt")
router.register(r"expenses", ExpenseViewSet, basename="expense")

urlpatterns = [
    path("", include(router.urls)),
]