"""
Production serializers for examinations administration.

All write operations are delegated to
reports.services.seating_service.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from reports.exceptions import ValidationError as DomainValidationError
from reports.models.examinations_admin import (
    InvigilatorAssignment,
    SeatAssignment,
    SeatingPlan,
)
from reports.services import seating_service


MAX_TEXT_LENGTH = 1_000
MAX_STUDENT_IDS = 10_000


def _request(serializer: serializers.BaseSerializer):
    request = serializer.context.get("request")
    if request is None:
        raise serializers.ValidationError(
            "Serializer request context is required."
        )
    return request


def _school(serializer: serializers.BaseSerializer):
    request = _request(serializer)
    school = getattr(request.user, "school", None)

    if school is None and not getattr(
        request.user,
        "is_superuser",
        False,
    ):
        raise serializers.ValidationError(
            "The authenticated user is not assigned to a school."
        )

    return school


def _as_serializer_error(
    exc: Exception,
) -> serializers.ValidationError:
    if hasattr(exc, "message_dict"):
        return serializers.ValidationError(exc.message_dict)
    if hasattr(exc, "messages"):
        return serializers.ValidationError(exc.messages)
    return serializers.ValidationError(str(exc))


class SeatingPlanSerializer(serializers.ModelSerializer):
    school_id = serializers.IntegerField(
        source="school_id",
        read_only=True,
    )
    created_by_id = serializers.IntegerField(
        source="created_by_id",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = SeatingPlan
        fields = (
            "id",
            "school_id",
            "external_reference",
            "room",
            "exam_date",
            "start_time",
            "end_time",
            "capacity",
            "created_by_id",
        )
        read_only_fields = (
            "id",
            "school_id",
            "created_by_id",
        )

    def validate_external_reference(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "external_reference cannot be blank."
            )
        return value

    def validate_room(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "room cannot be blank."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start_time = attrs.get(
            "start_time",
            getattr(self.instance, "start_time", None),
        )
        end_time = attrs.get(
            "end_time",
            getattr(self.instance, "end_time", None),
        )
        capacity = attrs.get(
            "capacity",
            getattr(self.instance, "capacity", None),
        )

        if (
            start_time is not None
            and end_time is not None
            and end_time <= start_time
        ):
            raise serializers.ValidationError(
                {
                    "end_time": (
                        "end_time must be after start_time."
                    )
                }
            )

        if capacity is not None and capacity <= 0:
            raise serializers.ValidationError(
                {
                    "capacity": (
                        "capacity must be greater than zero."
                    )
                }
            )

        try:
            seating_service.validate_seating_plan(
                school=_school(self),
                actor=_request(self).user,
                instance=self.instance,
                values=attrs,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

        return attrs

    def create(
        self,
        validated_data: dict[str, Any],
    ) -> SeatingPlan:
        request = _request(self)

        try:
            return seating_service.create_seating_plan(
                school=_school(self),
                created_by=request.user,
                **validated_data,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

    def update(
        self,
        instance: SeatingPlan,
        validated_data: dict[str, Any],
    ) -> SeatingPlan:
        request = _request(self)

        try:
            return seating_service.update_seating_plan(
                seating_plan=instance,
                updated_by=request.user,
                changes=validated_data,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc


class SeatAssignmentSerializer(serializers.ModelSerializer):
    seating_plan_id = serializers.PrimaryKeyRelatedField(
        source="seating_plan",
        queryset=SeatingPlan.objects.none(),
        write_only=True,
    )
    student_id = serializers.IntegerField(
        write_only=True,
        min_value=1,
    )
    assigned_student_id = serializers.IntegerField(
        source="student_id",
        read_only=True,
    )

    class Meta:
        model = SeatAssignment
        fields = (
            "id",
            "seating_plan_id",
            "student_id",
            "assigned_student_id",
            "seat_number",
            "subject_or_paper",
            "special_needs_accommodation",
            "status",
        )
        read_only_fields = (
            "id",
            "assigned_student_id",
        )

    def get_fields(self):
        fields = super().get_fields()
        school = _school(self)

        queryset = SeatingPlan.objects.all()
        if school is not None:
            queryset = queryset.filter(school=school)

        fields["seating_plan_id"].queryset = queryset
        return fields

    def validate_seat_number(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "seat_number cannot be blank."
            )
        return value

    def validate_subject_or_paper(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "subject_or_paper cannot be blank."
            )
        return value

    def validate_special_needs_accommodation(
        self,
        value: str,
    ) -> str:
        value = value.strip()
        if len(value) > MAX_TEXT_LENGTH:
            raise serializers.ValidationError(
                f"special_needs_accommodation may not exceed "
                f"{MAX_TEXT_LENGTH} characters."
            )
        return value

    def validate(
        self,
        attrs: dict[str, Any],
    ) -> dict[str, Any]:
        student_id = attrs.pop("student_id")
        attrs["_student_id"] = student_id

        try:
            seating_service.validate_seat_assignment(
                school=_school(self),
                actor=_request(self).user,
                instance=self.instance,
                seating_plan=attrs.get(
                    "seating_plan",
                    getattr(self.instance, "seating_plan", None),
                ),
                student_id=student_id,
                values=attrs,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

        return attrs

    def create(
        self,
        validated_data: dict[str, Any],
    ) -> SeatAssignment:
        student_id = validated_data.pop("_student_id")
        request = _request(self)

        try:
            return seating_service.assign_seat(
                school=_school(self),
                assigned_by=request.user,
                student_id=student_id,
                **validated_data,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

    def update(
        self,
        instance: SeatAssignment,
        validated_data: dict[str, Any],
    ) -> SeatAssignment:
        student_id = validated_data.pop(
            "_student_id",
            instance.student_id,
        )
        request = _request(self)

        try:
            return seating_service.update_seat_assignment(
                assignment=instance,
                updated_by=request.user,
                student_id=student_id,
                changes=validated_data,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc


class InvigilatorAssignmentSerializer(
    serializers.ModelSerializer
):
    seating_plan_id = serializers.PrimaryKeyRelatedField(
        source="seating_plan",
        queryset=SeatingPlan.objects.none(),
        write_only=True,
    )
    staff_id = serializers.IntegerField(
        write_only=True,
        min_value=1,
    )
    assigned_staff_id = serializers.IntegerField(
        source="staff_id",
        read_only=True,
    )

    class Meta:
        model = InvigilatorAssignment
        fields = (
            "id",
            "seating_plan_id",
            "staff_id",
            "assigned_staff_id",
            "role",
            "assigned_at",
        )
        read_only_fields = (
            "id",
            "assigned_staff_id",
            "assigned_at",
        )

    def get_fields(self):
        fields = super().get_fields()
        school = _school(self)

        queryset = SeatingPlan.objects.all()
        if school is not None:
            queryset = queryset.filter(school=school)

        fields["seating_plan_id"].queryset = queryset
        return fields

    def validate_role(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "role cannot be blank."
            )
        return value

    def validate(
        self,
        attrs: dict[str, Any],
    ) -> dict[str, Any]:
        staff_id = attrs.pop("staff_id")
        attrs["_staff_id"] = staff_id

        try:
            seating_service.validate_invigilator_assignment(
                school=_school(self),
                actor=_request(self).user,
                instance=self.instance,
                seating_plan=attrs.get(
                    "seating_plan",
                    getattr(self.instance, "seating_plan", None),
                ),
                staff_id=staff_id,
                role=attrs.get(
                    "role",
                    getattr(self.instance, "role", None),
                ),
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

        return attrs

    def create(
        self,
        validated_data: dict[str, Any],
    ) -> InvigilatorAssignment:
        staff_id = validated_data.pop("_staff_id")
        request = _request(self)

        try:
            return seating_service.assign_invigilator(
                school=_school(self),
                assigned_by=request.user,
                staff_id=staff_id,
                **validated_data,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

    def update(
        self,
        instance: InvigilatorAssignment,
        validated_data: dict[str, Any],
    ) -> InvigilatorAssignment:
        staff_id = validated_data.pop(
            "_staff_id",
            instance.staff_id,
        )
        request = _request(self)

        try:
            return seating_service.update_invigilator_assignment(
                assignment=instance,
                updated_by=request.user,
                staff_id=staff_id,
                changes=validated_data,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc


class MarkMissingCandidatesRequestSerializer(
    serializers.Serializer
):
    present_student_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        max_length=MAX_STUDENT_IDS,
    )

    def validate_present_student_ids(
        self,
        value: list[int],
    ) -> list[int]:
        counts = Counter(value)
        duplicates = sorted(
            student_id
            for student_id, count in counts.items()
            if count > 1
        )

        if duplicates:
            raise serializers.ValidationError(
                "Duplicate student IDs are not allowed."
            )

        return value

    def validate(
        self,
        attrs: dict[str, Any],
    ) -> dict[str, Any]:
        seating_plan = self.context.get("seating_plan")
        if seating_plan is None:
            raise serializers.ValidationError(
                "Seating plan context is required."
            )

        try:
            seating_service.validate_present_candidates(
                seating_plan=seating_plan,
                present_student_ids=attrs["present_student_ids"],
                marked_by=_request(self).user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc

        return attrs

    def save(self, **kwargs):
        seating_plan = kwargs.get(
            "seating_plan",
            self.context.get("seating_plan"),
        )
        if seating_plan is None:
            raise serializers.ValidationError(
                "Seating plan context is required."
            )

        try:
            return seating_service.mark_missing_candidates(
                seating_plan=seating_plan,
                present_student_ids=self.validated_data[
                    "present_student_ids"
                ],
                marked_by=_request(self).user,
            )
        except (
            DomainValidationError,
            DjangoValidationError,
        ) as exc:
            raise _as_serializer_error(exc) from exc