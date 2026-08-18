from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
import hashlib

from .models import (
    ClassRepresentativeAssignment,
    Announcement,
    GroupSet,
    StudyGroup,
    Poll,
    PollOption,
    PollVote,
    StudentFeedback,
    AuditLog,
)
from .serializers import (
    ClassRepAssignmentSerializer,
    AnnouncementSerializer,
    GroupSetSerializer,
    PollSerializer,
    StudentFeedbackSerializer,
    AuditLogSerializer,
)
from .permissions import IsClassRep, IsLecturerOrAdmin
from .services.ai_service import query_class_ai, ai_draft_announcement, ai_summarize_feedback

class ClassRepAssignmentViewSet(viewsets.ModelViewSet):
    queryset = ClassRepresentativeAssignment.objects.all()
    serializer_class = ClassRepAssignmentSerializer
    permission_classes = [IsAuthenticated, IsLecturerOrAdmin]

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


class AnnouncementViewSet(viewsets.ModelViewSet):
    serializer_class = AnnouncementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['LECTURER', 'ADMIN']:
            return Announcement.objects.all()
        # Students see published announcements or their own drafts
        return Announcement.objects.filter(status='PUBLISHED') | Announcement.objects.filter(created_by=user)

    def perform_create(self, serializer):
        user = self.request.user
        # Lecturers & Admins publish immediately; Reps submit for review
        initial_status = 'PUBLISHED' if user.role in ['LECTURER', 'ADMIN'] else 'PENDING_REVIEW'
        serializer.save(created_by=user, status=initial_status)

    @action(detail=True, methods=['post'], permission_classes=[IsLecturerOrAdmin])
    def review(self, request, pk=None):
        announcement = self.get_object()
        action_type = request.data.get('action') # 'APPROVE' or 'REJECT'
        reason = request.data.get('rejection_reason', '')

        if action_type == 'APPROVE':
            announcement.status = 'PUBLISHED'
            announcement.published_at = timezone.now()
            announcement.rejection_reason = None
        else:
            announcement.status = 'REJECTED'
            announcement.rejection_reason = reason

        announcement.reviewed_by = request.user
        announcement.reviewed_at = timezone.now()
        announcement.save()

        return Response(self.get_serializer(announcement).data)


class GroupSetViewSet(viewsets.ModelViewSet):
    queryset = GroupSet.objects.all()
    serializer_class = GroupSetSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PollViewSet(viewsets.ModelViewSet):
    queryset = Poll.objects.all()
    serializer_class = PollSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def vote(self, request, pk=None):
        poll = self.get_object()
        option_id = request.data.get('option_id')
        vote_type = request.data.get('vote_type', 'OPTION')

        # Generate cryptographic salt hash
        voter_hash = hashlib.sha256(f"{request.user.id}_{poll.id}_asms_salt".encode()).hexdigest()

        if PollVote.objects.filter(poll=poll, voter_hash=voter_hash).exists():
            return Response({'error': 'You have already voted in this poll.'}, status=status.HTTP_400_BAD_REQUEST)

        option = None
        if option_id:
            option = PollOption.objects.get(id=option_id, poll=poll)
            option.vote_count += 1
            option.save()

        PollVote.objects.create(
            poll=poll,
            student=None if poll.is_anonymous else getattr(request.user, 'student_profile', None),
            voter_hash=voter_hash,
            option=option,
            vote_type=vote_type,
        )

        return Response({'success': True, 'poll': self.get_serializer(poll).data})


class StudentFeedbackViewSet(viewsets.ModelViewSet):
    queryset = StudentFeedback.objects.all()
    serializer_class = StudentFeedbackSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        student_profile = getattr(self.request.user, 'student_profile', None)
        serializer.save(student=student_profile)

    @action(detail=True, methods=['post'], permission_classes=[IsLecturerOrAdmin])
    def respond(self, request, pk=None):
        feedback = self.get_object()
        feedback.status = request.data.get('status', 'RESOLVED')
        feedback.admin_response = request.data.get('admin_response', '')
        feedback.resolved_at = timezone.now()
        feedback.save()
        return Response(self.get_serializer(feedback).data)


# -------------------------------------------------------------
# AI ASSISTANT ENDPOINTS
# -------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ai_query(request):
    prompt = request.data.get('prompt')
    history = request.data.get('conversation_history', [])
    if not prompt:
        return Response({'error': 'Prompt is required'}, status=status.HTTP_400_BAD_REQUEST)

    reply = query_class_ai(request.user, prompt, history)
    return Response({'reply': reply})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ai_draft(request):
    raw_notes = request.data.get('raw_notes', '')
    subject_code = request.data.get('subject_code', 'General')
    urgency = request.data.get('urgency', 'NORMAL')

    result = ai_draft_announcement(raw_notes, subject_code, urgency)
    return Response(result)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsLecturerOrAdmin])
def ai_summary(request):
    summary = ai_summarize_feedback()
    return Response({'summary': summary})
