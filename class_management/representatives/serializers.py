"""
Serializers skeleton for representatives.

These are placeholders to be completed during implementation. They keep the
scaffold small and reviewable and avoid creating migrations or touching
settings.
"""

from rest_framework import serializers


class RepresentativeAssignmentSerializer(serializers.Serializer):
    student_profile_id = serializers.IntegerField()
    classroom_id = serializers.IntegerField(required=False, allow_null=True)
    classroom_subject_id = serializers.IntegerField(required=False, allow_null=True)
    academic_term_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)

