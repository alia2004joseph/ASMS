from rest_framework.routers import DefaultRouter

from .views import (
    AssessmentTypeViewSet,
    AssessmentViewSet,
    GradeViewSet,
    GradeHistoryViewSet,
    SubjectGradeApprovalViewSet,
)

router = DefaultRouter()

router.register(
    r"assessment-types",
    AssessmentTypeViewSet,
    basename="assessment-type",
)

router.register(
    r"assessments",
    AssessmentViewSet,
    basename="assessment",
)

router.register(
    r"grades",
    GradeViewSet,
    basename="grade",
)

router.register(
    r"grade-history",
    GradeHistoryViewSet,
    basename="grade-history",
)

router.register(
    r"subject-approvals",
    SubjectGradeApprovalViewSet,
    basename="subject-approval",
)

urlpatterns = router.urls