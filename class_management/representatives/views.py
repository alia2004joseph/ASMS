"""
Views skeleton for representative assignment APIs.

These views are lightweight placeholders that will be wired to actual logic
once the app is approved to be added to INSTALLED_APPS and migrations are
performed. They intentionally avoid importing model classes at module import
time to keep the scaffold safe and reversible.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from ..representatives import serializers as rep_serializers
from ..permissions.classes import IsAdminUser


class AssignRepresentativeView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def post(self, request, format=None):
        serializer = rep_serializers.RepresentativeAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Implementation note: service must validate student membership and
        # create ClassRepresentativeAssignment inside a transaction. This
        # scaffold does not perform DB writes.
        return Response({"detail": "Representative assignment received (dry-run scaffold)."}, status=status.HTTP_201_CREATED)


class ListRepresentativesView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def get(self, request, format=None):
        # Implementation note: return list of assignments for admin view
        return Response({"results": []})
