

# reports/services/report_authorization_service.py

from __future__ import annotations


def can_view_report(*, user, report) -> bool:
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return getattr(user, "school_id", None) == getattr(report, "school_id", None)


def can_export_report(*, user, report=None) -> bool:
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if report is not None:
        if getattr(user, "school_id", None) != getattr(report, "school_id", None):
            return False

    return getattr(user, "role", None) in {
        "ADMIN",
        "TEACHER",
        "ACCOUNTANT",
    }


def can_manage_report(*, user, report=None) -> bool:
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if report is not None:
        if getattr(user, "school_id", None) != getattr(report, "school_id", None):
            return False

    return getattr(user, "role", None) == "ADMIN"