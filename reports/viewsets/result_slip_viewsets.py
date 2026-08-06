"""
Production API views for result slips.
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
from reports.models.result_slips import ResultSlip
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.result_slip_serializers import (
    ResultSlipGenerateRequestSerializer,
    ResultSlipRegenerateRequestSerializer,
    ResultSlipRevokeRequestSerializer,
    ResultSlipSerializer,
    ResultSlipVerifyResponseSerializer,
)
from reports.services import result_slip_service, signature_service


class ResultSlipViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Generate, list, regenerate, revoke, and verify result slips.
    """

    permission_classes = (IsAuthenticated, BaseReportPermission)

    queryset = (
        ResultSlip.objects
        .select_related(
            "school", "student__user", "academic_year", "term", "classroom",
        )
        .filter(is_latest=True)
        .order_by("-created_at", "-pk")
    )

    serializer_class = ResultSlipSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user.is_superuser:
            return qs

        return qs.filter(school_id=self.request.user.school_id)

    def get_serializer_class(self):
        if self.action == "create":
            return ResultSlipGenerateRequestSerializer
        if self.action == "regenerate":
            return ResultSlipRegenerateRequestSerializer
        if self.action == "revoke":
            return ResultSlipRevokeRequestSerializer
        if self.action == "verify":
            return ResultSlipVerifyResponseSerializer
        return ResultSlipSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def create(self, request, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        slip = request_serializer.save()

        response_serializer = ResultSlipSerializer(
            slip, context=self.get_serializer_context(),
        )
        return Response(
            response_serializer.data, status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        student_id = request.query_params.get("student_id")
        queryset = self.filter_queryset(self.get_queryset())

        if student_id:
            queryset = queryset.filter(student_id=student_id)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ResultSlipSerializer(
                page, many=True, context=self.get_serializer_context(),
            )
            return self.get_paginated_response(serializer.data)

        serializer = ResultSlipSerializer(
            queryset, many=True, context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @action(detail=True, methods=("post",), url_path="regenerate")
    def regenerate(self, request, pk=None):
        previous = self.get_object()
        self.check_object_permissions(request, previous)

        request_serializer = self.get_serializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "result_slip": previous,
            },
        )
        request_serializer.is_valid(raise_exception=True)
        slip = request_serializer.save(previous=previous)

        response_serializer = ResultSlipSerializer(
            slip, context=self.get_serializer_context(),
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=("post",), url_path="revoke")
    def revoke(self, request, pk=None):
        slip = self.get_object()
        self.check_object_permissions(request, slip)

        request_serializer = self.get_serializer(
            data=request.data,
            context={**self.get_serializer_context(), "result_slip": slip},
        )
        request_serializer.is_valid(raise_exception=True)
        revoked = request_serializer.save(slip=slip)

        response_serializer = ResultSlipSerializer(
            revoked, context=self.get_serializer_context(),
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=("get",),
        url_path=r"verify/(?P<code>[^/.]+)",
        permission_classes=(AllowAny,),
        authentication_classes=(),
    )
    def verify(self, request, code=None):
        result = result_slip_service.verify(code)
        serializer = ResultSlipVerifyResponseSerializer(
            result, context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    # -- rendering -----------------------------------------------------

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

    def build_result_slip_context(self, request, slip):
        school = slip.school
        student = slip.student
        student_user = student.user

        signature_context = signature_service.build_signature_context(
            school,
            DocumentType.RESULT_SLIP,
        )
        signature_image = signature_context.get("signature_image")
        stamp_image = signature_context.get("stamp_image")

        verification_url = request.build_absolute_uri(
            f"/api/reports/result-slips/verify/{slip.verification_code}/"
        )

        return {
            "student_name": (
                student_user.get_full_name().strip()
                or student_user.email
            ),
            "student_number": getattr(student, "student_id_number", ""),
            "classroom": str(slip.classroom),
            "academic_year": str(slip.academic_year),
            "term": str(slip.term),
            "document_number": slip.verification_code,
            "created_at": slip.created_at,

            "subjects_snapshot": slip.subjects_snapshot,
            "aggregate_or_gpa": slip.aggregate_or_gpa,
            "position": slip.position,
            "class_average": slip.class_average,
            "pass_fail_status": slip.pass_fail_status,

            "signatory_name": (
                signature_context.get("signatory_name")
                or "Class Teacher"
            ),
            "signatory_title": (
                signature_context.get("signatory_title")
                or "Class Teacher"
            ),
            "signature_image": signature_image,
            "stamp_image": stamp_image,

            "verification_code": slip.verification_code,
            "verification_reference": slip.verification_code,
            "verification_url": verification_url,
            "qr_code_url": self._generate_qr_data_uri(verification_url),

            "document_version": slip.version,
            "document_fingerprint": slip.file_hash,

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

    def _render_result_slip_pdf(self, request, slip):
        context = self.build_result_slip_context(request, slip)
        html_string = render_to_string(
            "reports/result_slip/document.html", context, request=request,
        )

        pdf_buffer = BytesIO()
        HTML(
            string=html_string,
            base_url=request.build_absolute_uri("/"),
        ).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        ResultSlip.objects.filter(pk=slip.pk).update(
            file_hash=file_hash,
            file_size=len(pdf_bytes),
            mime_type="application/pdf",
            export_format="PDF",
        )
        slip.file_hash = file_hash

        return BytesIO(pdf_bytes)

    @action(
        detail=True, methods=["get"], url_path="html-preview",
        permission_classes=(AllowAny,),
    )
    def html_preview(self, request, pk=None):
        slip = get_object_or_404(
            ResultSlip.objects.select_related(
                "school", "student__user", "academic_year", "term",
                "classroom",
            ),
            pk=pk,
        )
        context = self.build_result_slip_context(request, slip)
        return render(request, "reports/result_slip/document.html", context)

    @action(
        detail=True, methods=["get"], url_path="pdf",
        permission_classes=(AllowAny,),
    )
    def pdf(self, request, pk=None):
        slip = get_object_or_404(
            ResultSlip.objects.select_related(
                "school", "student__user", "academic_year", "term",
                "classroom",
            ),
            pk=pk,
        )
        pdf_buffer = self._render_result_slip_pdf(request, slip)
        filename = f"result-slip-{slip.verification_code}.pdf"
        return FileResponse(
            pdf_buffer, as_attachment=False, filename=filename,
            content_type="application/pdf",
        )

    @action(
        detail=True, methods=["get"], url_path="download",
        permission_classes=(AllowAny,),
    )
    def download(self, request, pk=None):
        slip = get_object_or_404(
            ResultSlip.objects.select_related(
                "school", "student__user", "academic_year", "term",
                "classroom",
            ),
            pk=pk,
        )
        pdf_buffer = self._render_result_slip_pdf(request, slip)
        filename = f"result-slip-{slip.verification_code}.pdf"
        return FileResponse(
            pdf_buffer, as_attachment=True, filename=filename,
            content_type="application/pdf",
        )
