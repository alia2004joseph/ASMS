import hashlib
from io import BytesIO

from django.apps import apps
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from weasyprint import HTML

from reports.constants import DocumentType
from reports.exceptions import ValidationError as ServiceValidationError
from reports.models.transcripts import TranscriptRecord
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.transcript_serializers import (
    TranscriptGenerateRequestSerializer,
    TranscriptRecordSerializer,
    TranscriptRegenerateRequestSerializer,
    TranscriptVerifyResponseSerializer,
)
from reports.services import signature_service, transcript_service


class TranscriptViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, BaseReportPermission]

    @staticmethod
    def _generate_qr_data_uri(value: str) -> str:
        import base64

        import qrcode

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

    def build_transcript_context(self, request, transcript):
        school = transcript.school

        signature_context = signature_service.build_signature_context(
            school,
            DocumentType.TRANSCRIPT,
        )
        signature_image = signature_context.get("signature_image")
        stamp_image = signature_context.get("stamp_image")

        verification_url = request.build_absolute_uri(
            f"/api/reports/transcripts/verify/"
            f"{transcript.verification_code}/"
        )

        return {
            "is_official": transcript.is_official,
            "student_name": transcript.student_name_snapshot,
            "student_number": transcript.identification_number_snapshot,
            "cumulative_gpa": transcript.cumulative_gpa,
            "credits_earned_total": transcript.credits_earned_total,
            "gpa_snapshots": transcript.gpa_snapshots.all(),
            "programme_name": transcript.programme_snapshot,
            "school_or_faculty_name": school.name,
            "document_number": transcript.verification_code,
            "created_at": transcript.issued_at or transcript.created_at,

            "signatory_name": (
                signature_context.get("signatory_name")
                or "Registrar"
            ),
            "signatory_title": (
                signature_context.get("signatory_title")
                or "Registrar"
            ),
            "signature_image": signature_image,
            "stamp_image": stamp_image,

            "verification_code": transcript.verification_code,
            "verification_reference": transcript.verification_code,
            "verification_url": verification_url,
            "qr_code_url": self._generate_qr_data_uri(verification_url),

            "document_version": transcript.version,
            "document_fingerprint": transcript.file_hash,

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
                "microtext": f"{school.name} • OFFICIAL TRANSCRIPT",
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

    def _render_transcript_pdf(self, request, transcript):
        context = self.build_transcript_context(request, transcript)
        html_string = render_to_string(
            "reports/transcript/document.html",
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
        TranscriptRecord.objects.filter(pk=transcript.pk).update(
            file_hash=file_hash,
            file_size=len(pdf_bytes),
            mime_type="application/pdf",
            export_format="PDF",
        )
        transcript.file_hash = file_hash

        return BytesIO(pdf_bytes)

    @action(
        detail=True,
        methods=["get"],
        url_path="html-preview",
        permission_classes=[AllowAny],
    )
    def html_preview(self, request, pk=None):
        transcript = get_object_or_404(
            TranscriptRecord.objects.select_related("school", "student"),
            pk=pk,
        )
        context = self.build_transcript_context(request, transcript)
        return render(request, "reports/transcript/document.html", context)

    @action(
        detail=True,
        methods=["get"],
        url_path="pdf",
        permission_classes=[AllowAny],
    )
    def pdf(self, request, pk=None):
        transcript = get_object_or_404(
            TranscriptRecord.objects.select_related("school", "student"),
            pk=pk,
        )
        pdf_buffer = self._render_transcript_pdf(request, transcript)
        filename = f"transcript-{transcript.verification_code}.pdf"
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
        transcript = get_object_or_404(
            TranscriptRecord.objects.select_related("school", "student"),
            pk=pk,
        )
        pdf_buffer = self._render_transcript_pdf(request, transcript)
        filename = f"transcript-{transcript.verification_code}.pdf"
        return FileResponse(
            pdf_buffer,
            as_attachment=True,
            filename=filename,
            content_type="application/pdf",
        )

    def _get_student(self, request, student_id):
        Student = apps.get_model("students", "Student")
        return Student.objects.get(pk=student_id, school=request.user.school)

    def _get_terms(self, term_ids):
        Term = apps.get_model("academics", "Term")
        terms = list(Term.objects.filter(pk__in=term_ids).order_by("pk"))
        if len(terms) != len(set(term_ids)):
            raise ServiceValidationError("One or more term_ids could not be resolved.")
        return terms

    def create(self, request):
        serializer = TranscriptGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        student = self._get_student(request, data["student_id"])
        terms = self._get_terms(data["term_ids"])

        transcript = transcript_service.generate_transcript(
            student=student, school=request.user.school, terms=terms,
            is_official=data["is_official"], issued_by=request.user,
        )
        return Response(TranscriptRecordSerializer(transcript).data, status=status.HTTP_201_CREATED)

    def list(self, request):
        student_id = request.query_params.get("student_id")
        student = self._get_student(request, student_id)
        self.check_object_permissions(
            request, type("Obj", (), {"student_id": student.pk, "school_id": request.user.school_id})()
        )
        transcripts = TranscriptRecord.objects.filter(
            school=request.user.school, student=student, is_latest=True
        ).prefetch_related("gpa_snapshots")
        return Response(TranscriptRecordSerializer(transcripts, many=True).data)

    def retrieve(self, request, pk=None):
        transcript = TranscriptRecord.objects.prefetch_related("gpa_snapshots").get(
            pk=pk, school=request.user.school
        )
        self.check_object_permissions(request, transcript)
        return Response(TranscriptRecordSerializer(transcript).data)

    @action(detail=True, methods=["get"], url_path="versions")
    def versions(self, request, pk=None):
        transcript = TranscriptRecord.objects.get(pk=pk, school=request.user.school)
        self.check_object_permissions(request, transcript)
        chain = TranscriptRecord.objects.filter(root_id=transcript.root_id).order_by("version")
        return Response(TranscriptRecordSerializer(chain, many=True).data)

    @action(detail=True, methods=["post"], url_path="regenerate")
    def regenerate(self, request, pk=None):
        previous = TranscriptRecord.objects.get(pk=pk, school=request.user.school)
        self.check_object_permissions(request, previous)
        serializer = TranscriptRegenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        terms = self._get_terms(data["term_ids"])
        try:
            new_transcript = transcript_service.regenerate_transcript(
                previous=previous, reason=data["reason"], terms=terms, generated_by=request.user
            )
        except ServiceValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(TranscriptRecordSerializer(new_transcript).data)

    @action(detail=False, methods=["get"], url_path="verify/(?P<code>[^/.]+)", permission_classes=[AllowAny])
    def verify(self, request, code=None):
        result = transcript_service.verify(code)
        return Response(TranscriptVerifyResponseSerializer(result).data)
