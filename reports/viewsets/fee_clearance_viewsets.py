"""
Production API views for fee-clearance certificates.

Views remain thin:
- permissions authorize access;
- serializers validate input and delegate writes to services;
- services own business rules and cross-app integrations;
- querysets enforce school isolation.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO

import qrcode
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from weasyprint import HTML

from reports.constants import DocumentType
from reports.models.fee_clearance import FeeClearanceCertificate
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.fee_clearance_serializers import (
    FeeClearanceCertificateSerializer,
    FeeClearanceIssueRequestSerializer,
    FeeClearanceRegenerateRequestSerializer,
    FeeClearanceRevokeRequestSerializer,
    FeeClearanceVerifyResponseSerializer,
)
from reports.services import fee_clearance_service, signature_service


class FeeClearanceCertificateViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Issue, list, regenerate, revoke, and verify fee-clearance certificates.
    """

    permission_classes = (
        IsAuthenticated,
        BaseReportPermission,
    )

    queryset = (
        FeeClearanceCertificate.objects
        .select_related(
            "school",
            "student",
            "academic_year",
            "term",
            "issued_by",
            "revoked_by",
        )
        .filter(is_latest=True)
        .order_by("-issued_at", "-pk")
    )

    serializer_class = FeeClearanceCertificateSerializer

    def get_queryset(self):
        user = self.request.user

        queryset = super().get_queryset()

        if getattr(user, "is_superuser", False):
            return queryset

        return queryset.filter(school_id=user.school_id)

    def get_serializer_class(self):
        if self.action == "create":
            return FeeClearanceIssueRequestSerializer

        if self.action == "regenerate":
            return FeeClearanceRegenerateRequestSerializer

        if self.action == "revoke":
            return FeeClearanceRevokeRequestSerializer

        if self.action == "verify":
            return FeeClearanceVerifyResponseSerializer

        return FeeClearanceCertificateSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    @staticmethod
    def _generate_qr_data_uri(value: str) -> str:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(value)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    def build_fee_clearance_context(self, request, certificate):
        school = certificate.school
        student = certificate.student
        student_user = student.user

        signature_context = signature_service.build_signature_context(
            school,
            DocumentType.FEE_CLEARANCE,
        )
        signature_image = signature_context.get("signature_image")
        stamp_image = signature_context.get("stamp_image")

        verification_url = request.build_absolute_uri(
            f"/api/reports/fee-clearance/verify/"
            f"{certificate.verification_code}/"
        )

        return {
            "student_name": (
                student_user.get_full_name().strip()
                or student_user.email
            ),
            "student_number": getattr(student, "student_id_number", ""),
            "academic_year": str(certificate.academic_year),
            "term": str(certificate.term),
            "certificate_number": certificate.certificate_number,
            "document_number": certificate.certificate_number,
            "issued_at": (
                certificate.issued_at.strftime("%d %B %Y")
                if certificate.issued_at
                else "Not yet issued"
            ),
            "created_at": certificate.issued_at or certificate.created_at,
            "cleared_amount": certificate.cleared_amount,
            "outstanding_balance": certificate.outstanding_balance,
            "clearance_status": certificate.clearance_status,
            "override_reason": certificate.override_reason,

            "signatory_name": (
                signature_context.get("signatory_name")
                or "Finance Officer"
            ),
            "signatory_title": (
                signature_context.get("signatory_title")
                or "Finance Officer"
            ),
            "signature_image": signature_image,
            "stamp_image": stamp_image,

            "verification_code": certificate.verification_code,
            "verification_reference": certificate.verification_code,
            "verification_url": verification_url,
            "qr_code_url": self._generate_qr_data_uri(verification_url),

            "document_version": certificate.version,
            "document_fingerprint": certificate.file_hash,

            "school_name": school.name,
            "branding": {
                "school_name": school.name,
                "school_address": getattr(school, "address", "") or "",
                "school_phone": getattr(school, "phone", "") or "",
                "school_email": getattr(school, "email", "") or "",
                "font_family": "DejaVu Sans, Arial, sans-serif",
                "heading_font_family": "Georgia, Times New Roman, serif",
                "font_size_base": "10.5pt",
                "watermark_text": school.name,
                "microtext": f"{school.name} • OFFICIAL DOCUMENT",
                "colors": {
                    "primary": "#173b63",
                    "secondary": "#5f6976",
                    "accent": "#d3aa4d",
                },
            },
            "page_config": {
                "page_size": "A4",
                "orientation": "portrait",
                "margins": {
                    "top": "15mm",
                    "right": "15mm",
                    "bottom": "15mm",
                    "left": "15mm",
                },
            },
            "layout_config": {},
        }

    def _render_fee_clearance_pdf(self, request, certificate):
        context = self.build_fee_clearance_context(request, certificate)
        html_string = render_to_string(
            "reports/fee_clearance/document.html",
            context,
            request=request,
        )

        pdf_buffer = BytesIO()
        HTML(
            string=html_string,
            base_url=request.build_absolute_uri("/"),
        ).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        FeeClearanceCertificate.objects.filter(pk=certificate.pk).update(
            file_hash=file_hash,
            file_size=len(pdf_bytes),
            mime_type="application/pdf",
            export_format="PDF",
        )
        certificate.file_hash = file_hash

        return BytesIO(pdf_bytes)

    @action(
        detail=True,
        methods=("get",),
        url_path="html-preview",
        permission_classes=(AllowAny,),
    )
    def html_preview(self, request, pk=None):
        certificate = get_object_or_404(
            FeeClearanceCertificate.objects.select_related(
                "school", "student__user", "academic_year", "term",
            ),
            pk=pk,
        )
        context = self.build_fee_clearance_context(request, certificate)
        return render(
            request, "reports/fee_clearance/document.html", context,
        )

    @action(
        detail=True,
        methods=("get",),
        url_path="pdf",
        permission_classes=(AllowAny,),
    )
    def pdf(self, request, pk=None):
        certificate = get_object_or_404(
            FeeClearanceCertificate.objects.select_related(
                "school", "student__user", "academic_year", "term",
            ),
            pk=pk,
        )
        pdf_buffer = self._render_fee_clearance_pdf(request, certificate)
        filename = f"fee-clearance-{certificate.certificate_number}.pdf"
        return FileResponse(
            pdf_buffer,
            as_attachment=False,
            filename=filename,
            content_type="application/pdf",
        )

    @action(
        detail=True,
        methods=("get",),
        url_path="download",
        permission_classes=(AllowAny,),
    )
    def download(self, request, pk=None):
        certificate = get_object_or_404(
            FeeClearanceCertificate.objects.select_related(
                "school", "student__user", "academic_year", "term",
            ),
            pk=pk,
        )
        pdf_buffer = self._render_fee_clearance_pdf(request, certificate)
        filename = f"fee-clearance-{certificate.certificate_number}.pdf"
        return FileResponse(
            pdf_buffer,
            as_attachment=True,
            filename=filename,
            content_type="application/pdf",
        )

    def create(self, request, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        certificate = request_serializer.save()

        response_serializer = FeeClearanceCertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        student_id = request.query_params.get("student_id")

        certificates = fee_clearance_service.list_fee_clearance_certificates(
            school=request.user.school,
            requested_by=request.user,
            student_id=student_id,
            latest_only=True,
        )

        page = self.paginate_queryset(certificates)
        if page is not None:
            serializer = FeeClearanceCertificateSerializer(
                page,
                many=True,
                context=self.get_serializer_context(),
            )
            return self.get_paginated_response(serializer.data)

        serializer = FeeClearanceCertificateSerializer(
            certificates,
            many=True,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @action(
        detail=True,
        methods=("post",),
        url_path="regenerate",
    )
    def regenerate(self, request, pk=None):
        previous = self.get_object()
        self.check_object_permissions(request, previous)

        request_serializer = self.get_serializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "certificate": previous,
            },
        )
        request_serializer.is_valid(raise_exception=True)

        certificate = request_serializer.save(previous=previous)

        response_serializer = FeeClearanceCertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )
        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=("post",),
        url_path="revoke",
    )
    def revoke(self, request, pk=None):
        certificate = self.get_object()
        self.check_object_permissions(request, certificate)

        request_serializer = self.get_serializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "certificate": certificate,
            },
        )
        request_serializer.is_valid(raise_exception=True)

        revoked_certificate = request_serializer.save(
            certificate=certificate,
        )

        response_serializer = FeeClearanceCertificateSerializer(
            revoked_certificate,
            context=self.get_serializer_context(),
        )
        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=("get",),
        url_path=r"verify/(?P<code>[^/.]+)",
        permission_classes=(AllowAny,),
        authentication_classes=(),
    )
    def verify(self, request, code=None):
        result = fee_clearance_service.verify_fee_clearance_certificate(
            code=code,
        )

        serializer = FeeClearanceVerifyResponseSerializer(
            result,
            context=self.get_serializer_context(),
        )
        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )