"""
Signal registration for the Reports module.

This module intentionally exposes an explicit, idempotent registration
function instead of relying on import-time side effects.

Actual receivers should be added only when their corresponding service APIs
are implemented. Signal handlers must remain thin and delegate all work to
services such as cache invalidation or analytics stale-marking.
"""

from __future__ import annotations

from threading import Lock

_registration_lock = Lock()
_registered = False


def register_reports_signals() -> None:
    """
    Register Reports signal receivers exactly once.

    This function is safe to call repeatedly, including during Django's
    autoreloader cycle.

    Add future receiver registration inside this function using stable
    ``dispatch_uid`` values. Signal receivers must not contain business logic;
    they should delegate immediately to the appropriate Reports service.
    """
    global _registered

    if _registered:
        return

    with _registration_lock:
        if _registered:
            return

        # Future registrations belong here.
        #
        # Example pattern:
        #
        # from django.db.models.signals import post_delete, post_save
        # from reports.models.generated_reports import GeneratedReport
        # from reports.signals.receivers import (
        #     generated_report_deleted,
        #     generated_report_saved,
        # )
        #
        # post_save.connect(
        #     generated_report_saved,
        #     sender=GeneratedReport,
        #     dispatch_uid="reports.generated_report.post_save",
        # )
        #
        # post_delete.connect(
        #     generated_report_deleted,
        #     sender=GeneratedReport,
        #     dispatch_uid="reports.generated_report.post_delete",
        # )

        _registered = True