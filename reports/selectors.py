"""
Centralized read querysets for the Reports module.

All reusable read-side ORM construction belongs here so school isolation,
relationship loading, ordering, and version-chain behavior remain consistent
across services and API endpoints.

Business decisions do not belong in this module. These helpers only construct
optimized querysets or return explicitly requested read objects.
"""

from __future__ import annotations

from typing import TypeVar

from django.db import models
from django.db.models import Q, QuerySet

from reports.models.bulk_jobs import BulkExportArchive, BulkReportJob
from reports.models.custom_reports import CustomReportDefinition
from reports.models.fee_clearance import FeeClearanceCertificate
from reports.models.generated_reports import GeneratedReport
from reports.models.report_definitions import ReportTemplate
from reports.models.result_slips import ResultSlip
from reports.models.signatures import DocumentSignatureAssignment

ModelT = TypeVar("ModelT", bound=models.Model)


def get_custom_report_definitions_for_user(
    *,
    user,
    school,
) -> QuerySet[CustomReportDefinition]:
    """
    Return report definitions visible to a user within one school.

    Visibility includes:
    - public definitions for the school;
    - private definitions owned by the requesting user.
    """
    return (
        CustomReportDefinition.objects
        .filter(school=school)
        .filter(Q(is_public=True) | Q(owner=user))
        .select_related(
            "school",
            "owner",
        )
        .prefetch_related(
            "fields",
            "filters",
            "sorts",
            "groups",
        )
        .distinct()
        .order_by("name", "pk")
    )


def get_signature_assignments(
    *,
    school,
    document_type: str,
) -> QuerySet[DocumentSignatureAssignment]:
    """
    Return active signature assignments for a document type.
    """
    return (
        DocumentSignatureAssignment.objects
        .filter(
            school=school,
            document_type=document_type,
            is_active=True,
        )
        .select_related(
            "school",
            "signatory",
            "signature",
            "stamp",
        )
        .order_by("pk")
    )


def get_signature_assignment(
    *,
    school,
    document_type: str,
) -> DocumentSignatureAssignment | None:
    """
    Return the first active signature assignment for a document type.
    """
    return get_signature_assignments(
        school=school,
        document_type=document_type,
    ).first()


def get_report_templates(
    *,
    school,
    document_type: str,
    active_only: bool = True,
) -> QuerySet[ReportTemplate]:
    """
    Return templates for a school and document type, newest version first.
    """
    queryset = (
        ReportTemplate.objects
        .filter(
            school=school,
            document_type=document_type,
        )
        .select_related("school")
        .order_by("-version", "-pk")
    )

    if active_only:
        queryset = queryset.filter(is_active=True)

    return queryset


def get_latest_template(
    *,
    school,
    document_type: str,
) -> ReportTemplate | None:
    """
    Return the highest-version active template for a document type.
    """
    return get_report_templates(
        school=school,
        document_type=document_type,
        active_only=True,
    ).first()


def get_version_chain(
    *,
    model_cls: type[ModelT],
    root_id,
    school=None,
) -> QuerySet[ModelT]:
    """
    Return a complete document version chain ordered from oldest to newest.

    `school` should be supplied for school-owned models. It remains optional
    only to support globally scoped versioned models.
    """
    queryset = model_cls.objects.filter(root_id=root_id)

    if school is not None:
        queryset = queryset.filter(school=school)

    return queryset.order_by("version", "pk")


def get_result_slips_for_student(
    *,
    student,
    school,
    latest_only: bool = True,
) -> QuerySet[ResultSlip]:
    """
    Return result slips for one student within one school.
    """
    queryset = (
        ResultSlip.objects
        .filter(
            school=school,
            student=student,
        )
        .select_related(
            "school",
            "student",
            "term",
            "academic_year",
            "class_ref",
        )
        .order_by("-term_id", "-version", "-pk")
    )

    if latest_only:
        queryset = queryset.filter(is_latest=True)

    return queryset


def get_result_slips_for_class(
    *,
    class_ref,
    school,
    latest_only: bool = True,
) -> QuerySet[ResultSlip]:
    """
    Return result slips for one class within one school.
    """
    queryset = (
        ResultSlip.objects
        .filter(
            school=school,
            class_ref=class_ref,
        )
        .select_related(
            "school",
            "student",
            "term",
            "academic_year",
            "class_ref",
        )
        .order_by("student_id", "-term_id", "-version", "-pk")
    )

    if latest_only:
        queryset = queryset.filter(is_latest=True)

    return queryset


def get_fee_clearance_for_student(
    *,
    student,
    school,
    latest_only: bool = True,
) -> QuerySet[FeeClearanceCertificate]:
    """
    Return fee-clearance certificates for one student within one school.
    """
    queryset = (
        FeeClearanceCertificate.objects
        .filter(
            school=school,
            student=student,
        )
        .select_related(
            "school",
            "student",
            "term",
            "academic_year",
        )
        .order_by("-term_id", "-version", "-pk")
    )

    if latest_only:
        queryset = queryset.filter(is_latest=True)

    return queryset


def get_bulk_jobs(
    *,
    school,
) -> QuerySet[BulkReportJob]:
    """
    Return optimized bulk-report jobs for a school.
    """
    return (
        BulkReportJob.objects
        .filter(school=school)
        .select_related("school")
        .prefetch_related("items")
        .order_by("-pk")
    )


def get_bulk_job(
    *,
    job_id,
    school,
) -> BulkReportJob | None:
    """
    Return one school-scoped bulk-report job.
    """
    return get_bulk_jobs(
        school=school,
    ).filter(pk=job_id).first()


def get_bulk_archive(
    *,
    job_id,
    school,
) -> BulkExportArchive | None:
    """
    Return the archive produced for a school-scoped bulk-report job.
    """
    return (
        BulkExportArchive.objects
        .filter(
            school=school,
            job_id=job_id,
        )
        .select_related(
            "school",
            "job",
        )
        .order_by("-pk")
        .first()
    )


def get_generated_reports_for_user(
    *,
    user,
    school,
    role: str | None = None,
    latest_only: bool = True,
) -> QuerySet[GeneratedReport]:
    """
    Return the school-scoped base queryset for generated reports.

    Role-specific ownership and guardian/student/teacher visibility must be
    applied by the calling service or permission-aware queryset policy.
    The `role` argument is retained for backward compatibility and must not
    weaken school isolation.
    """
    del user, role

    queryset = (
        GeneratedReport.objects
        .filter(school=school)
        .select_related(
            "school",
            "report_type",
            "requested_by",
        )
        .order_by("-created_at", "-pk")
    )

    if latest_only:
        queryset = queryset.filter(is_latest=True)

    return queryset