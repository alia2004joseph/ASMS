# accounts/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from .views import (
    AccessCodeViewSet,
    AccountApprovalView,
    BulkAccountApprovalView,
    CurrentUserView,
    CustomLoginView,
    GuardianStudentLinkViewSet,
    PendingAccountListView,
    ProfileView,
    RegisterView,
)

router = DefaultRouter()
router.register("access-codes", AccessCodeViewSet, basename="access-code")
router.register(
    "guardian-links", GuardianStudentLinkViewSet, basename="guardian-link"
)

app_name = "accounts"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    # JWT login/refresh/verify. CustomLoginView issues the initial pair;
    # refresh/verify come straight from simplejwt since nothing in
    # views.py overrides them.
    path("login/", CustomLoginView.as_view(), name="login"),
    path("login/refresh/", TokenRefreshView.as_view(), name="login-refresh"),
    path("login/verify/", TokenVerifyView.as_view(), name="login-verify"),
    path("me/", CurrentUserView.as_view(), name="me"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("pending/", PendingAccountListView.as_view(), name="pending-users"),
    path(
        "pending/<int:user_id>/action/",
        AccountApprovalView.as_view(),
        name="approve-reject-user",
    ),
    path(
        "pending/bulk-action/",
        BulkAccountApprovalView.as_view(),
        name="bulk-approve-reject-users",
    ),
    path("", include(router.urls)),
]