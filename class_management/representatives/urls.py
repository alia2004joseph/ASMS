from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClassRepAssignmentViewSet,
    AnnouncementViewSet,
    GroupSetViewSet,
    PollViewSet,
    StudentFeedbackViewSet,
    ai_query,
    ai_draft,
    ai_summary,
)

router = DefaultRouter()
router.register(r'representatives', ClassRepAssignmentViewSet, basename='class-rep-assignments')
router.register(r'announcements', AnnouncementViewSet, basename='announcements')
router.register(r'groups', GroupSetViewSet, basename='group-sets')
router.register(r'polls', PollViewSet, basename='polls')
router.register(r'feedback', StudentFeedbackViewSet, basename='student-feedback')

urlpatterns = [
    path('', include(router.urls)),
    # AI Assistant Endpoints
    path('ai/query/', ai_query, name='ai-query'),
    path('ai/draft-announcement/', ai_draft, name='ai-draft-announcement'),
    path('ai/summarize-feedback/', ai_summary, name='ai-summarize-feedback'),
]
