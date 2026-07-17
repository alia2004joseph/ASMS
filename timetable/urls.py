# timetable/urls.py

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PeriodViewSet, TimetableEntryViewSet

router = DefaultRouter()
router.register(r"periods", PeriodViewSet, basename="period")
router.register(r"entries", TimetableEntryViewSet, basename="timetableentry")

urlpatterns = [
    path("", include(router.urls)),
]