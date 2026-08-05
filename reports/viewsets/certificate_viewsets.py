from django.shortcuts import get_object_or_404, render
import base64
from io import BytesIO

import qrcode

from io import BytesIO

from django.http import FileResponse
from django.template.loader import render_to_string
from weasyprint import HTML
import hashlib



from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from reports.models.certificates import Certificate, CertificateTemplate
from reports.permissions.report_permissions import (
    BaseReportPermission,
    CanManageSignatures,
)
from reports.serializers.certificate_serializers import (
    CertificateIssueRequestSerializer,
    CertificateRevokeRequestSerializer,
    CertificateSerializer,
    CertificateTemplateSerializer,
    CertificateVerifyResponseSerializer,
)
from reports.services import certificate_service


class CertificateTemplateViewSet(viewsets.ModelViewSet):
    """
    Certificate template management.

    All create/update/delete logic is delegated to the serializer,
    which delegates to certificate_service.
    """

    serializer_class = CertificateTemplateSerializer
    permission_classes = [IsAuthenticated, CanManageSignatures]

    def get_queryset(self):
        return (
            CertificateTemplate.objects
            .filter(school=self.request.user.school)
            .order_by("name")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    @staticmethod
    def generate_qr_data_uri(value: str) -> str:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )

        qr.add_data(value)
        qr.make(fit=True)

        image = qr.make_image(
            fill_color="black",
            back_color="white",
        )

        buffer = BytesIO()
        image.save(buffer, format="PNG")

        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return f"data:image/png;base64,{encoded}"


class CertificateViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Certificate API.

    Views contain no business logic.

    Services perform all work.
    """

    permission_classes = [
        IsAuthenticated,
        BaseReportPermission,
    ]

    queryset = (
        Certificate.objects
        .select_related(
            "student",
            "school",
        )
        .filter(is_latest=True)
    )

    serializer_class = CertificateSerializer

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            return Certificate.objects.none()

        if user.is_superuser:
            return Certificate.objects.all()

        school = getattr(user, "school", None)

        if school is None:
            return Certificate.objects.none()

        return Certificate.objects.filter(school=school)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_serializer_class(self):

        if self.action == "create":
            return CertificateIssueRequestSerializer

        if self.action == "revoke":
            return CertificateRevokeRequestSerializer

        if self.action == "verify":
            return CertificateVerifyResponseSerializer

        return CertificateSerializer

    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(
            data=request.data,
            context=self.get_serializer_context(),
        )

        serializer.is_valid(raise_exception=True)

        certificate = serializer.save()

        output = CertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )

        return Response(
            output.data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):

        queryset = certificate_service.list_certificates(
            school=request.user.school,
            student_id=request.query_params.get("student_id"),
            user=request.user,
        )

        serializer = CertificateSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(serializer.data)

    def build_certificate_context(self, request, certificate):
        school = certificate.school
        student = certificate.student
        student_user = student.user

        verification_url = request.build_absolute_uri(
            f"/api/reports/certificates/verify/"
            f"{certificate.verification_code}/"
        )

        return {
            "certificate_type_display": (
                certificate.get_certificate_type_display()
            ),
            "student_name": (
                student_user.get_full_name().strip()
                or student_user.email
            ),
            "student_number": student.student_id_number,
            "citation_text": (
                "In recognition of outstanding achievement and the successful "
                "fulfilment of the institution's academic requirements."
            ),
            "serial_number": certificate.serial_number,
            "issued_at": (
                certificate.issued_at.strftime("%d %B %Y")
                if certificate.issued_at
                else "Not yet issued"
            ),
            "school_name": school.name,

            "headteacher_name": "Authorised Signatory",
            "headteacher_title": "Headteacher",
            "headteacher_signature_url": "",
            "stamp_url": "",

            "verification_code": certificate.verification_code,
            "verification_url": verification_url,
            "qr_code_url": CertificateTemplateViewSet.generate_qr_data_uri(verification_url),

            "branding": {
                "school_name": school.name,
                "school_motto": "",
                "school_address": school.address or "",
                "school_phone": school.phone or "",
                "school_email": school.email or "",
                "logo_url": "",

                "font_family": "DejaVu Sans, Arial, sans-serif",
                "heading_font_family": "Georgia, Times New Roman, serif",
                "font_size_base": "10.5pt",

                "background_image": "",
                "watermark_image": "",
                "watermark_text": school.name,

                "colors": {
                    "primary": "#173b63",
                    "secondary": "#5f6976",
                    "accent": "#d3aa4d",
                },
            },

            "page_config": {
                "page_size": "A4",
                "orientation": "landscape",
                "margins": {
                    "top": "12mm",
                    "right": "12mm",
                    "bottom": "12mm",
                    "left": "12mm",
                },
            },

            "layout_config": certificate.template.layout_config or {},
        }

    def _generate_certificate_pdf(self, request, certificate):
        context = self.build_certificate_context(
            request=request,
            certificate=certificate,
        )

        html_string = render_to_string(
            "reports/certificate/document.html",
            context,
            request=request,
        )

        pdf_bytes = HTML(
            string=html_string,
            base_url=request.build_absolute_uri("/"),
        ).write_pdf()

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

        Certificate.objects.filter(pk=certificate.pk).update(
            file_hash=file_hash,
            file_size=len(pdf_bytes),
            mime_type="application/pdf",
            export_format="PDF",
        )

        certificate.file_hash = file_hash
        certificate.file_size = len(pdf_bytes)
        certificate.mime_type = "application/pdf"
        certificate.export_format = "PDF"

        return BytesIO(pdf_bytes)

    @action(
        detail=True,
        methods=["post"],
        permission_classes =[AllowAny]
    )
    def revoke(self, request, pk=None):
        certificate = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
            context={
                **self.get_serializer_context(),
                "certificate": certificate,
            },
        )
        serializer.is_valid(raise_exception=True)

        certificate = serializer.save()

        output = CertificateSerializer(
            certificate,
            context=self.get_serializer_context(),
        )

        return Response(output.data)
    
@action(
    detail=False,
    methods=["get"],
    url_path="template-preview",
    permission_classes=[AllowAny],
)
def template_preview(self, request):
    verification_url = (
        "http://127.0.0.1:8000/api/reports/"
        "certificates/verify/CERT-2026-000001/"
    )
    context = {
        "certificate_type_display": "Certificate of Academic Excellence",
        "student_name": "Joseph Alia",
        "school_id_number": "25/U/08624/PS",
        "citation_text": (
            "In recognition of outstanding academic performance, exemplary "
            "discipline, and successful fulfilment of the institution's "
            "academic requirements."
        ),

        "serial_number": "CERT-2026-000001",
        "issued_at": "29 July 2026",
        "student_number": "25/U/08624/PS",
        "school_name": "ALIA Demonstration Secondary School",

        "headteacher_name": "Dr Sarah Namusoke",
        "headteacher_title": "Headteacher",

        "headteacher_signature_url": (
            "/static/reports/images/demo-signature.png"
        ),
        "stamp_url": "/static/reports/images/demo-stamp.png",
        "verification_code": "CERT-2026-000001",
        "verification_url": verification_url,
        "qr_code_url": CertificateTemplateViewSet.generate_qr_data_uri(
            verification_url
        ),

        "branding": {
            "school_name": "ALIA Demonstration Secondary School",
            "school_motto": "Knowledge, Discipline and Excellence",
            "school_address": "Kampala, Uganda",
            "school_phone": "+256 700 000000",
            "school_email": "info@aliaschool.ac.ug",

            "font_family": "'DejaVu Sans', Arial, sans-serif",
            "heading_font_family": "Georgia, 'Times New Roman', serif",
            "font_size_base": "10.5pt",

            "logo_url": "/static/reports/images/demo-school-logo.png",
            "background_image": "",
            "watermark_image": "",
            "watermark_text": "ALIA",

            "colors": {
                "primary": "#173b63",
                "secondary": "#5f6976",
                "accent": "#d3aa4d",
            },
        },

        "page_config": {
            "page_size": "A4",
            "orientation": "landscape",
            "margins": {
                "top": "12mm",
                "right": "12mm",
                "bottom": "12mm",
                "left": "12mm",
            },
        },

        "layout_config": {},
    }

    return render(
        request,
        "reports/certificate/document.html",
        context,
    )

    @action(
        detail=True,
        methods=["get"],
        url_path="html-preview",
        permission_classes=[AllowAny],
    )
    def html_preview(self, request, pk=None):
        certificate = get_object_or_404(
            Certificate.objects.select_related(
                "student__user",
                "school",
                "template",
            ),
            pk=pk,
        )

        context = self.build_certificate_context(
            request=request,
            certificate=certificate,
        )

        return render(
            request,
            "reports/certificate/document.html",
            context,
        )

    @action(
    detail=False,
    methods=["get"],
    url_path=r"verify/(?P<verification_code>[^/.]+)",
    permission_classes=[AllowAny],
    authentication_classes=[],
)
    def verify(self, request, verification_code=None):
        certificate = (
            Certificate.objects.select_related(
                "student__user",
                "school",
                "template",
            )
            .filter(verification_code=verification_code)
            .first()
        )

        if certificate is None:
            context = {
                "is_valid": False,
                "branding": {
                    "font_family": "'DejaVu Sans', Arial, sans-serif",
                    "heading_font_family": "Georgia, 'Times New Roman', serif",
                    "font_size_base": "10.5pt",
                    "background_image": "",
                    "watermark_image": "",
                    "watermark_text": "",
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
                        "top": "20mm",
                        "right": "20mm",
                        "bottom": "20mm",
                        "left": "20mm",
                    },
                },
                "layout_config": {},
            }

            return render(
                request,
                "reports/certificate/verification.html",
                context,
                status=404,
            )

        student = certificate.student
        student_user = student.user
        school = certificate.school

        context = {
            "is_valid": True,
            "student_name": (
                student_user.get_full_name().strip()
                or student_user.email
            ),
            "student_number": student.student_id_number,
            "certificate_type_display": (
                certificate.get_certificate_type_display()
            ),
            "serial_number": certificate.serial_number,
            "verification_code": certificate.verification_code,
            "issued_at": (
                certificate.issued_at.strftime("%d %B %Y")
                if certificate.issued_at
                else "Not issued"
            ),
            "school_name": school.name,

            "branding": {
                "font_family": "'DejaVu Sans', Arial, sans-serif",
                "heading_font_family": "Georgia, 'Times New Roman', serif",
                "font_size_base": "10.5pt",
                "background_image": "",
                "watermark_image": "",
                "watermark_text": school.name,
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
                    "top": "20mm",
                    "right": "20mm",
                    "bottom": "20mm",
                    "left": "20mm",
                },
            },

            "layout_config": {},
            "document_hash": certificate.file_hash,
"integrity_status": (
    "Fingerprint recorded"
    if certificate.file_hash
    else "Fingerprint not yet recorded"
),
"is_revoked": certificate.is_revoked,
"revoked_reason": certificate.revoked_reason,
        }

        return render(
            request,
            "reports/certificate/verification.html",
            context,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="pdf",
        permission_classes=[AllowAny],
    )
    def pdf(self, request, pk=None):
        certificate = get_object_or_404(
            Certificate.objects.select_related(
                "student__user",
                "school",
                "template",
            ),
            pk=pk,
        )

        context = self.build_certificate_context(
            request=request,
            certificate=certificate,
        )

        html_string = render_to_string(
            "reports/certificate/document.html",
            context,
            request=request,
        )

        pdf_buffer = BytesIO()

        HTML(
            string=html_string,
            base_url=request.build_absolute_uri("/"),
        ).write_pdf(pdf_buffer)

        pdf_buffer.seek(0)

        student_name = (
            certificate.student.user.get_full_name().strip()
            or "student"
        )

        filename = (
            f"{certificate.serial_number}-"
            f"{student_name}.pdf"
        )

        safe_filename = (
            filename.replace(" ", "-")
            .replace("/", "-")
            .replace("\\", "-")
        )

        return FileResponse(
            pdf_buffer,
            as_attachment=False,
            filename=safe_filename,
            content_type="application/pdf",
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="pdf-preview",
        permission_classes=[AllowAny],
    )
    def pdf_preview(self, request, pk=None):
        certificate = get_object_or_404(
            Certificate.objects.select_related(
                "student__user",
                "school",
                "template",
            ),
            pk=pk,
        )

        pdf_buffer = self._generate_certificate_pdf(
            request,
            certificate,
        )

        filename = f"{certificate.serial_number}.pdf"

        return FileResponse(
            pdf_buffer,
            as_attachment=False,
            filename=filename,
            content_type="application/pdf",
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="download",
        permission_classes=[AllowAny],
    )
    def download(self, request, pk=None):
        certificate = get_object_or_404(
            Certificate.objects.select_related(
                "student__user",
                "school",
                "template",
            ),
            pk=pk,
        )

        pdf_buffer = self._generate_certificate_pdf(
            request,
            certificate,
        )

        student_name = (
            certificate.student.user.get_full_name().strip()
            or "student"
        )

        filename = (
            f"{certificate.serial_number}-"
            f"{student_name}.pdf"
        )

        safe_filename = (
            filename.replace(" ", "-")
            .replace("/", "-")
            .replace("\\", "-")
        )

        return FileResponse(
            pdf_buffer,
            as_attachment=True,
            filename=safe_filename,
            content_type="application/pdf",
        )