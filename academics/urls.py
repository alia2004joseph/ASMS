# academics/urls.py

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AcademicYearViewSet,
    AcademicTermViewSet,
    ClassroomViewSet,
    SubjectViewSet,
    ClassroomSubjectViewSet,
    StudentEnrollmentViewSet,
)

router = DefaultRouter()

router.register(
    r"academic-years",
    AcademicYearViewSet,
    basename="academic-year",
)

router.register(
    r"academic-terms",
    AcademicTermViewSet,
    basename="academic-term",
)

router.register(
    r"classrooms",
    ClassroomViewSet,
    basename="classroom",
)

router.register(
    r"subjects",
    SubjectViewSet,
    basename="subject",
)

router.register(
    r"classroom-subjects",
    ClassroomSubjectViewSet,
    basename="classroom-subject",
)

router.register(
    r"enrollments",
    StudentEnrollmentViewSet,
    basename="enrollment",
)

urlpatterns = [
    path("", include(router.urls)),
]