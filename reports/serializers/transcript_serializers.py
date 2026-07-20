"""
Production serializers for transcript generation, regeneration and verification.
Business logic is delegated to transcript_service.
"""
from __future__ import annotations

from collections import Counter
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from reports.constants import VerificationResult
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.transcripts import TranscriptGPASnapshot, TranscriptRecord
from reports.services import transcript_service


def _req(s):
    r=s.context.get("request")
    if r is None:
        raise serializers.ValidationError("Request context is required.")
    return r

def _school(s):
    r=_req(s)
    school=getattr(r.user,"school",None)
    if school is None and not getattr(r.user,"is_superuser",False):
        raise serializers.ValidationError("Authenticated user has no school.")
    return school

def _err(exc):
    if hasattr(exc,"message_dict"):
        return serializers.ValidationError(exc.message_dict)
    if hasattr(exc,"messages"):
        return serializers.ValidationError(exc.messages)
    return serializers.ValidationError(str(exc))


class TranscriptGenerateRequestSerializer(serializers.Serializer):
    student_id=serializers.IntegerField(min_value=1)
    term_ids=serializers.ListField(child=serializers.IntegerField(min_value=1),allow_empty=False)
    is_official=serializers.BooleanField(default=False)

    def validate_term_ids(self,v):
        dup=[k for k,c in Counter(v).items() if c>1]
        if dup:
            raise serializers.ValidationError("Duplicate term IDs are not allowed.")
        return v

    def create(self,validated_data):
        try:
            return transcript_service.generate_transcript_from_ids(
                school=_school(self),
                issued_by=_req(self).user,
                **validated_data
            )
        except (DomainValidationError,DjangoValidationError) as exc:
            raise _err(exc)


class TranscriptRegenerateRequestSerializer(serializers.Serializer):
    reason=serializers.CharField(min_length=3,max_length=2000,trim_whitespace=True)
    term_ids=serializers.ListField(child=serializers.IntegerField(min_value=1),allow_empty=False)

    def validate_term_ids(self,v):
        if len(v)!=len(set(v)):
            raise serializers.ValidationError("Duplicate term IDs are not allowed.")
        return v

    def save(self,**kwargs):
        previous=kwargs.get("previous",self.context.get("transcript"))
        if previous is None:
            raise serializers.ValidationError("Transcript context is required.")
        try:
            return transcript_service.regenerate_transcript_from_ids(
                previous=previous,
                generated_by=_req(self).user,
                reason=self.validated_data["reason"],
                term_ids=self.validated_data["term_ids"],
            )
        except (DomainValidationError,DjangoValidationError) as exc:
            raise _err(exc)


class TranscriptGPASnapshotSerializer(serializers.ModelSerializer):
    term_id=serializers.IntegerField(source="term_id",read_only=True)

    class Meta:
        model=TranscriptGPASnapshot
        fields=(
            "term_id",
            "term_gpa",
            "cumulative_gpa",
            "credits_earned",
            "computed_at",
        )
        read_only_fields=fields


class TranscriptRecordSerializer(serializers.ModelSerializer):
    student_id=serializers.IntegerField(source="student_id",read_only=True)
    previous_version_id=serializers.IntegerField(source="previous_version_id",read_only=True,allow_null=True)
    issued_by_id=serializers.IntegerField(source="issued_by_id",read_only=True,allow_null=True)
    file_url=serializers.SerializerMethodField()
    gpa_snapshots=TranscriptGPASnapshotSerializer(many=True,read_only=True)

    class Meta:
        model=TranscriptRecord
        fields=(
            "id",
            "student_id",
            "is_official",
            "verification_code",
            "cumulative_gpa",
            "credits_earned_total",
            "version",
            "root_id",
            "previous_version_id",
            "is_latest",
            "is_revoked",
            "issued_at",
            "issued_by_id",
            "status",
            "file_url",
            "gpa_snapshots",
        )
        read_only_fields=fields

    def get_file_url(self,obj):
        f=getattr(obj,"file",None)
        if not f:
            return None
        try:
            url=f.url
        except Exception:
            return None
        req=self.context.get("request")
        return req.build_absolute_uri(url) if req else url


class TranscriptVerifyResponseSerializer(serializers.Serializer):
    result=serializers.ChoiceField(choices=VerificationResult.choices)
    student_id=serializers.IntegerField(required=False)
    is_official=serializers.BooleanField(required=False)
    cumulative_gpa=serializers.DecimalField(max_digits=5,decimal_places=3,required=False)
    version=serializers.IntegerField(required=False,min_value=1)