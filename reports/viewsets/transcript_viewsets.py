from django.apps import apps
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from reports.exceptions import ValidationError as ServiceValidationError
from reports.models.transcripts import TranscriptRecord
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.transcript_serializers import (
    TranscriptGenerateRequestSerializer,
    TranscriptRecordSerializer,
    TranscriptRegenerateRequestSerializer,
    TranscriptVerifyResponseSerializer,
)
from reports.services import transcript_service


class TranscriptViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, BaseReportPermission]

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
