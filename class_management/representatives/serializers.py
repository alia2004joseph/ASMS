from rest_framework import serializers
from .models import (
    ClassRepresentativeAssignment,
    Announcement,
    GroupSet,
    StudyGroup,
    GroupMember,
    Poll,
    PollOption,
    PollVote,
    StudentFeedback,
    AuditLog,
)

class ClassRepAssignmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.user.get_full_name', read_only=True)
    student_reg = serializers.CharField(source='student.reg_number', read_only=True)
    classroom_code = serializers.CharField(source='classroom.code', read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)

    class Meta:
        model = ClassRepresentativeAssignment
        fields = '__all__'


class AnnouncementSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    author_role = serializers.CharField(source='created_by.role', read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    reviewer_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)

    class Meta:
        model = Announcement
        fields = '__all__'
        read_only_fields = ('created_by', 'status', 'reviewed_by', 'reviewed_at', 'published_at')


class GroupMemberSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.user.get_full_name', read_only=True)
    reg_number = serializers.CharField(source='student.reg_number', read_only=True)

    class Meta:
        model = GroupMember
        fields = '__all__'


class StudyGroupSerializer(serializers.ModelSerializer):
    members = GroupMemberSerializer(source='memberships', many=True, read_only=True)

    class Meta:
        model = StudyGroup
        fields = '__all__'


class GroupSetSerializer(serializers.ModelSerializer):
    groups = StudyGroupSerializer(many=True, read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    author_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = GroupSet
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'published_at')


class PollOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PollOption
        fields = ('id', 'text', 'vote_count')


class PollSerializer(serializers.ModelSerializer):
    options = PollOptionSerializer(many=True, read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    author_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    has_voted = serializers.SerializerMethodField()

    class Meta:
        model = Poll
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at')

    def get_has_voted(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # Calculate voter hash for current user
        import hashlib
        voter_hash = hashlib.sha256(f"{request.user.id}_{obj.id}_asms_salt".encode()).hexdigest()
        return PollVote.objects.filter(poll=obj, voter_hash=voter_hash).exists()


class StudentFeedbackSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    subject_code = serializers.CharField(source='subject.code', read_only=True)

    class Meta:
        model = StudentFeedback
        fields = '__all__'
        read_only_fields = ('student', 'created_at', 'resolved_at')

    def get_student_name(self, obj):
        if obj.is_anonymous:
            return "Anonymous Student"
        return obj.student.user.get_full_name() if obj.student else "Enrolled Student"


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'
