"""
Production API views for ID Cards.
"""

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
from reports.models.id_cards import IDCard
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.id_card_serializers import (
    IDCardIssueRequestSerializer,
    IDCardRegenerateRequestSerializer,
    IDCardRevokeRequestSerializer,
    IDCardSerializer,
    IDCardVerifyResponseSerializer,
)
from reports.services import id_card_service, signature_service


class IDCardViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (IsAuthenticated, BaseReportPermission)
    serializer_class = IDCardSerializer

    queryset = (
        IDCard.objects.select_related("school")
        .filter(is_latest=True)
        .order_by("-created_at", "-pk")
    )

    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user.is_superuser:
            return qs

        return qs.filter(school=self.request.user.school)

    def get_serializer_class(self):
        if self.action == "create":
            return IDCardIssueRequestSerializer
        if self.action == "regenerate":
            return IDCardRegenerateRequestSerializer
        if self.action == "revoke":
            return IDCardRevokeRequestSerializer
        if self.action == "verify":
            return IDCardVerifyResponseSerializer
        return IDCardSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @staticmethod
    def _generate_qr_data_uri(value: str) -> str:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=1,
        )
        qr.add_data(value)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    def _shared_card_context(self, request, card):
        school = card.school
        return {
            "school_name": school.name,
            "branding": {
                "logo": getattr(school, "logo_url", "") or "",
                "colors": {
                    "primary": "#173b63",
                    "secondary": "#5f6976",
                },
                "website": getattr(school, "website", "") or "",
                "phone": getattr(school, "phone", "") or "",
            },
        }

    def build_front_context(self, request, card):
        role_context = card.role_context or {}
        verification_url = request.build_absolute_uri(
            f"/api/reports/id-cards/verify/{card.verification_code}/"
        )

        return {
            **self._shared_card_context(request, card),
            "holder_name": card.holder_name_snapshot,
            "identification_number": card.identification_number,
            "role_label": card.role_label,
            "classroom_or_department": (
                role_context.get("classroom")
                or role_context.get("department")
                or ""
            ),
            "valid_from": card.valid_from,
            "valid_until": card.valid_until,
            "qr_code_base64": self._generate_qr_data_uri(verification_url),
            "card_number": card.verification_code,
        }

    def build_back_context(self, request, card):
        school = card.school
        signature_context = signature_service.build_signature_context(
            school,
            DocumentType.ID_CARD,
        )
        emergency_contact = card.emergency_contact or {}

        return {
            **self._shared_card_context(request, card),
            "emergency_contact": emergency_contact,
            "stamp_image": signature_context.get("stamp_image"),
            "signature_image": signature_context.get("signature_image"),
            "signatory_name": signature_context.get("signatory_name") or "",
            "signatory_title": (
                signature_context.get("signatory_title")
                or "Administrator"
            ),
        }

    def _render_card_pdf(self, request, card):
        front_html = render_to_string(
            "reports/id_card/front.html",
            self.build_front_context(request, card),
            request=request,
        )
        back_html = render_to_string(
            "reports/id_card/back.html",
            self.build_back_context(request, card),
            request=request,
        )

        combined_html = f"""
        <html><body style="margin:0;">
            <div style="page-break-after: always;">{front_html}</div>
            <div>{back_html}</div>
        </body></html>
        """

        pdf_buffer = BytesIO()
        HTML(
            string=combined_html,
            base_url=request.build_absolute_uri("/"),
        ).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        IDCard.objects.filter(pk=card.pk).update(
            file_hash=file_hash,
            file_size=len(pdf_bytes),
            mime_type="application/pdf",
            export_format="PDF",
        )

        return BytesIO(pdf_bytes)

    @action(
        detail=True,
        methods=["get"],
        url_path="html-preview",
        permission_classes=(AllowAny,),
    )
    def html_preview(self, request, pk=None):
        card = get_object_or_404(IDCard.objects.select_related("school"), pk=pk)
        face = request.query_params.get("face", "front")
        template = (
            "reports/id_card/back.html"
            if face == "back"
            else "reports/id_card/front.html"
        )
        context = (
            self.build_back_context(request, card)
            if face == "back"
            else self.build_front_context(request, card)
        )
        return render(request, template, context)

    @action(
        detail=True,
        methods=["get"],
        url_path="pdf",
        permission_classes=(AllowAny,),
    )
    def pdf(self, request, pk=None):
        card = get_object_or_404(IDCard.objects.select_related("school"), pk=pk)
        pdf_buffer = self._render_card_pdf(request, card)
        filename = f"id-card-{card.verification_code}.pdf"
        return FileResponse(
            pdf_buffer, as_attachment=False, filename=filename,
            content_type="application/pdf",
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="download",
        permission_classes=(AllowAny,),
    )
    def download(self, request, pk=None):
        card = get_object_or_404(IDCard.objects.select_related("school"), pk=pk)
        pdf_buffer = self._render_card_pdf(request, card)
        filename = f"id-card-{card.verification_code}.pdf"
        return FileResponse(
            pdf_buffer, as_attachment=True, filename=filename,
            content_type="application/pdf",
        )

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        card = s.save()
        return Response(
            IDCardSerializer(card, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        cards = id_card_service.list_id_cards(
            school=request.user.school,
            requested_by=request.user,
            holder_type=request.query_params.get("holder_type"),
            holder_id=request.query_params.get("holder_id"),
            latest_only=True,
        )

        page = self.paginate_queryset(cards)
        if page is not None:
            return self.get_paginated_response(
                IDCardSerializer(
                    page,
                    many=True,
                    context=self.get_serializer_context(),
                ).data
            )

        return Response(
            IDCardSerializer(
                cards,
                many=True,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        card = self.get_object()
        self.check_object_permissions(request, card)

        s = self.get_serializer(
            data=request.data,
            context={**self.get_serializer_context(), "card": card},
        )
        s.is_valid(raise_exception=True)

        new_card = s.save(previous=card)

        return Response(
            IDCardSerializer(
                new_card,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        card = self.get_object()
        self.check_object_permissions(request, card)

        s = self.get_serializer(
            data=request.data,
            context={**self.get_serializer_context(), "card": card},
        )
        s.is_valid(raise_exception=True)

        revoked = s.save(card=card)

        return Response(
            IDCardSerializer(
                revoked,
                context=self.get_serializer_context(),
            ).data
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"verify/(?P<code>[^/.]+)",
        permission_classes=(AllowAny,),
        authentication_classes=(),
    )
    def verify(self, request, code=None):
        result = id_card_service.verify_id_card(code=code)
        return Response(
            IDCardVerifyResponseSerializer(
                result,
                context=self.get_serializer_context(),
            ).data
        )