"""
Production API views for ID Cards.
"""

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from reports.models.id_cards import IDCard
from reports.permissions.report_permissions import BaseReportPermission
from reports.serializers.id_card_serializers import (
    IDCardIssueRequestSerializer,
    IDCardRegenerateRequestSerializer,
    IDCardRevokeRequestSerializer,
    IDCardSerializer,
    IDCardVerifyResponseSerializer,
)
from reports.services import id_card_service


class IDCardViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (IsAuthenticated, BaseReportPermission)
    serializer_class = IDCardSerializer

    queryset = (
        IDCard.objects.select_related("school")
        .filter(is_latest=True)
        .order_by("-created_at", "-pk")
    )

    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user.is_superuser:
            return qs

        return qs.filter(school=self.request.user.school)

    def get_serializer_class(self):
        if self.action == "create":
            return IDCardIssueRequestSerializer
        if self.action == "regenerate":
            return IDCardRegenerateRequestSerializer
        if self.action == "revoke":
            return IDCardRevokeRequestSerializer
        if self.action == "verify":
            return IDCardVerifyResponseSerializer
        return IDCardSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        card = s.save()
        return Response(
            IDCardSerializer(card, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        cards = id_card_service.list_id_cards(
            school=request.user.school,
            requested_by=request.user,
            holder_type=request.query_params.get("holder_type"),
            holder_id=request.query_params.get("holder_id"),
            latest_only=True,
        )

        page = self.paginate_queryset(cards)
        if page is not None:
            return self.get_paginated_response(
                IDCardSerializer(
                    page,
                    many=True,
                    context=self.get_serializer_context(),
                ).data
            )

        return Response(
            IDCardSerializer(
                cards,
                many=True,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        card = self.get_object()
        self.check_object_permissions(request, card)

        s = self.get_serializer(
            data=request.data,
            context={**self.get_serializer_context(), "card": card},
        )
        s.is_valid(raise_exception=True)

        new_card = s.save(previous=card)

        return Response(
            IDCardSerializer(
                new_card,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        card = self.get_object()
        self.check_object_permissions(request, card)

        s = self.get_serializer(
            data=request.data,
            context={**self.get_serializer_context(), "card": card},
        )
        s.is_valid(raise_exception=True)

        revoked = s.save(card=card)

        return Response(
            IDCardSerializer(
                revoked,
                context=self.get_serializer_context(),
            ).data
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"verify/(?P<code>[^/.]+)",
        permission_classes=(AllowAny,),
        authentication_classes=(),
    )
    def verify(self, request, code=None):
        result = id_card_service.verify_id_card(code=code)
        return Response(
            IDCardVerifyResponseSerializer(
                result,
                context=self.get_serializer_context(),
            ).data
        )