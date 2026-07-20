"""
Production permission classes for the Reports module.

Permission classes remain thin and delegate all role, relationship, school,
category, and job-type authorization decisions to the Reports authorization
service.

List endpoints must still apply service-driven queryset scoping because DRF
does not run object permissions for every row in a collection.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

import reports.services.report_authorization_service as report_authorization_service

class BaseReportPermission(BasePermission):
    """
    Base Reports permission.

    Responsibilities:
    - require an authenticated user;
    - delegate object-level authorization to the service layer.

    Queryset visibility for list endpoints must be enforced separately by the
    relevant service or school-scoped queryset method.
    """

    message = "You do not have permission to access this report resource."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        return report_authorization_service.can_access_reports_endpoint(
            user=user,
            view=view,
            method=request.method,
        )

    def has_object_permission(self, request, view, obj) -> bool:
        return report_authorization_service.can_access_report_object(
            user=request.user,
            obj=obj,
            view=view,
            method=request.method,
        )


class CanUseCustomReportBuilder(BasePermission):
    """
    Authorize access to custom-report sources, definitions, previews,
    executions, and exports.
    """

    message = "You do not have permission to use the custom report builder."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        return report_authorization_service.can_use_custom_report_builder(
            user=user,
            view=view,
            method=request.method,
        )

    def has_object_permission(self, request, view, obj) -> bool:
        return report_authorization_service.can_access_custom_report_definition(
            user=request.user,
            definition=obj,
            view=view,
            method=request.method,
        )


class CanManageSignatures(BasePermission):
    """
    Authorize signature, stamp, and document-signatory administration.
    """

    message = "You do not have permission to manage report signatures."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        return report_authorization_service.can_manage_report_signatures(
            user=user,
            view=view,
            method=request.method,
        )

    def has_object_permission(self, request, view, obj) -> bool:
        return report_authorization_service.can_manage_signature_assignment(
            user=request.user,
            assignment=obj,
            view=view,
            method=request.method,
        )


class CanManageBulkJob(BasePermission):
    """
    Authorize bulk-report job creation, inspection, cancellation, finalization,
    archive access, and cleanup.
    """

    message = "You do not have permission to manage this bulk report job."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        job_type = None

        if request.method in {"POST", "PUT", "PATCH"}:
            job_type = request.data.get("job_type")

        return report_authorization_service.can_manage_bulk_report_jobs(
            user=user,
            job_type=job_type,
            view=view,
            method=request.method,
        )

    def has_object_permission(self, request, view, obj) -> bool:
        return report_authorization_service.can_access_bulk_report_job(
            user=request.user,
            job=obj,
            view=view,
            method=request.method,
        )


class CanAccessFinanceReports(BasePermission):
    """
    Restrict endpoints and objects containing finance-category report data.
    """

    message = "You do not have permission to access finance reports."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        return report_authorization_service.can_access_finance_reports(
            user=user,
            view=view,
            method=request.method,
        )

    def has_object_permission(self, request, view, obj) -> bool:
        return report_authorization_service.can_access_finance_report_object(
            user=request.user,
            obj=obj,
            view=view,
            method=request.method,
        )


class CanVerifyReportDocument(BasePermission):
    """
    Permission for public or authenticated document-verification endpoints.

    The authorization service decides whether a verification endpoint is
    public for the document type and deployment policy.
    """

    message = "You do not have permission to verify this document."

    def has_permission(self, request, view) -> bool:
        return report_authorization_service.can_verify_report_document(
            user=getattr(request, "user", None),
            view=view,
            method=request.method,
        )


class CanExportReports(BasePermission):
    """
    Authorize report export operations independently of read access.
    """

    message = "You do not have permission to export reports."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        return report_authorization_service.can_export_reports(
            user=user,
            view=view,
            method=request.method,
        )

    def has_object_permission(self, request, view, obj) -> bool:
        return report_authorization_service.can_export_report_object(
            user=request.user,
            obj=obj,
            view=view,
            method=request.method,
        )