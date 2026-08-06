"""
Production URL configuration for the Reports module.
"""


from rest_framework.routers import DefaultRouter

from reports.viewsets.certificate_viewsets import (
    CertificateTemplateViewSet,
    CertificateViewSet,
)
from reports.viewsets.custom_report_viewsets import (
    CustomReportDefinitionViewSet,
    CustomReportSourceViewSet,
)
from reports.viewsets.fee_clearance_viewsets import (
    FeeClearanceCertificateViewSet,
)
from reports.viewsets.id_card_viewsets import IDCardViewSet
from reports.viewsets.performance_history_viewsets import (
    PerformanceHistoryViewSet,
)
from reports.viewsets.result_slip_viewsets import ResultSlipViewSet
from reports.viewsets.seating_viewsets import (
    InvigilatorAssignmentViewSet,
    SeatAssignmentViewSet,
    SeatingPlanViewSet,
)
from reports.viewsets.transcript_viewsets import TranscriptViewSet

app_name = "reports"

router = DefaultRouter(trailing_slash=True)

# Custom Reports
router.register(
    r"custom/sources",
    CustomReportSourceViewSet,
    basename="custom-report-source",
)
router.register(
    r"custom/definitions",
    CustomReportDefinitionViewSet,
    basename="custom-report-definition",
)

# Certificates
router.register(
    r"certificates/templates",
    CertificateTemplateViewSet,
    basename="certificate-template",
)
router.register(
    r"certificates",
    CertificateViewSet,
    basename="certificate",
)

# Fee Clearance
router.register(
    r"fee-clearance",
    FeeClearanceCertificateViewSet,
    basename="fee-clearance",
)

# Transcripts
router.register(
    r"transcripts",
    TranscriptViewSet,
    basename="transcript",
)

# Result Slips
router.register(
    r"result-slips",
    ResultSlipViewSet,
    basename="result-slip",
)

# ID Cards
router.register(
    r"id-cards",
    IDCardViewSet,
    basename="id-card",
)

# Examination Administration
router.register(
    r"seating/plans",
    SeatingPlanViewSet,
    basename="seating-plan",
)
router.register(
    r"seating/assignments",
    SeatAssignmentViewSet,
    basename="seat-assignment",
)
router.register(
    r"seating/invigilators",
    InvigilatorAssignmentViewSet,
    basename="invigilator-assignment",
)

# Analytics
router.register(
    r"performance",
    PerformanceHistoryViewSet,
    basename="performance-history",
)

urlpatterns = router.urls

