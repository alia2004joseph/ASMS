# communications/urls.py

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CommunicationAttachmentViewSet,
    CommunicationTemplateViewSet,
    CommunicationViewSet,
    InboxViewSet,
    NotificationPreferenceView,
    UnreadCountView,
)

router = DefaultRouter()
router.register(r"communications", CommunicationViewSet, basename="communication")
router.register(r"attachments", CommunicationAttachmentViewSet, basename="communication_attachment")
router.register(r"templates", CommunicationTemplateViewSet, basename="communication_template")
router.register(r"inbox", InboxViewSet, basename="communication_inbox")

urlpatterns = [
    path("unread-count/", UnreadCountView.as_view(), name="communications_unread_count"),
    path("preferences/me/", NotificationPreferenceView.as_view(), name="communications_preferences_me"),
    path("", include(router.urls)),
]
