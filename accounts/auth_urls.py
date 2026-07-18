# accounts/auth_urls.py

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)

from .auth_views import (
    CurrentUserAPIView,
    LoginAPIView,
    LogoutAPIView,
    PasswordResetAPIView,
    SignupAPIView,
)


urlpatterns = [
    path(
        "login/",
        LoginAPIView.as_view(),
        name="auth-login",
    ),
    path(
        "refresh/",
        TokenRefreshView.as_view(),
        name="auth-refresh",
    ),
    path(
        "me/",
        CurrentUserAPIView.as_view(),
        name="auth-me",
    ),
    path(
        "signup/",
        SignupAPIView.as_view(),
        name="auth-signup",
    ),
    path(
        "password-reset/",
        PasswordResetAPIView.as_view(),
        name="auth-password-reset",
    ),
    path(
        "logout/",
        LogoutAPIView.as_view(),
        name="auth-logout",
    ),
]