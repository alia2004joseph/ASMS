"""
Production examinations administration viewsets.
"""
from rest_framework import mixins,status,viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reports.models.examinations_admin import SeatingPlan,SeatAssignment,InvigilatorAssignment
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.seating_serializers import (
    SeatingPlanSerializer,SeatAssignmentSerializer,
    InvigilatorAssignmentSerializer,
    MarkMissingCandidatesRequestSerializer,
)
from reports.services import seating_service,export_service


class SeatingPlanViewSet(viewsets.ModelViewSet):
    permission_classes=(IsAuthenticated,BaseReportPermission)
    serializer_class=SeatingPlanSerializer
    queryset=SeatingPlan.objects.select_related("school","created_by").order_by("-exam_date","room")

    def get_queryset(self):
        qs=super().get_queryset()
        return qs if self.request.user.is_superuser else qs.filter(school=self.request.user.school)

    def get_serializer_context(self):
        c=super().get_serializer_context(); c["request"]=self.request; return c

    def _plan(self): return self.get_object()

    @action(detail=True,methods=["get"])
    def room_list(self,request,pk=None):
        data=seating_service.get_room_list(self._plan(),request.user)
        return Response(SeatAssignmentSerializer(data,many=True,context=self.get_serializer_context()).data)

    @action(detail=True,methods=["get"],url_path="candidate-list")
    def candidate_list(self,request,pk=None):
        data=seating_service.get_candidate_list(self._plan(),request.user)
        return Response(SeatAssignmentSerializer(data,many=True,context=self.get_serializer_context()).data)

    @action(detail=True,methods=["get"],url_path="missing-candidates")
    def missing_candidates(self,request,pk=None):
        data=seating_service.get_missing_candidates(self._plan(),request.user)
        return Response(SeatAssignmentSerializer(data,many=True,context=self.get_serializer_context()).data)

    @action(detail=True,methods=["get"],url_path="special-needs")
    def special_needs(self,request,pk=None):
        data=seating_service.get_special_needs_candidates(self._plan(),request.user)
        return Response(SeatAssignmentSerializer(data,many=True,context=self.get_serializer_context()).data)

    @action(detail=True,methods=["get"])
    def invigilators(self,request,pk=None):
        data=seating_service.get_invigilators(self._plan(),request.user)
        return Response(InvigilatorAssignmentSerializer(data,many=True,context=self.get_serializer_context()).data)

    @action(detail=True,methods=["post"],url_path="mark-missing")
    def mark_missing(self,request,pk=None):
        plan=self._plan()
        s=MarkMissingCandidatesRequestSerializer(data=request.data,context={**self.get_serializer_context(),"seating_plan":plan})
        s.is_valid(raise_exception=True)
        result=s.save(seating_plan=plan)
        return Response(result,status=status.HTTP_200_OK)

    @action(detail=True,methods=["get"],url_path="room-list/export")
    def room_list_export(self,request,pk=None):
        payload=export_service.export_room_list(
            seating_plan=self._plan(),
            requested_by=request.user,
            export_format=request.query_params.get("format","EXCEL"),
        )
        return Response(payload,status=status.HTTP_200_OK)


class SeatAssignmentViewSet(viewsets.ModelViewSet):
    permission_classes=(IsAuthenticated,BaseReportPermission)
    serializer_class=SeatAssignmentSerializer
    queryset=SeatAssignment.objects.select_related("seating_plan").order_by("seat_number")
    def get_queryset(self):
        qs=super().get_queryset()
        return qs if self.request.user.is_superuser else qs.filter(seating_plan__school=self.request.user.school)
    def get_serializer_context(self):
        c=super().get_serializer_context(); c["request"]=self.request; return c


class InvigilatorAssignmentViewSet(viewsets.ModelViewSet):
    permission_classes=(IsAuthenticated,BaseReportPermission)
    serializer_class=InvigilatorAssignmentSerializer
    queryset=InvigilatorAssignment.objects.select_related("seating_plan","staff").order_by("assigned_at")
    def get_queryset(self):
        qs=super().get_queryset()
        return qs if self.request.user.is_superuser else qs.filter(seating_plan__school=self.request.user.school)
    def get_serializer_context(self):
        c=super().get_serializer_context(); c["request"]=self.request; return c