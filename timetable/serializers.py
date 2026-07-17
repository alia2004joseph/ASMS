# timetable/serializers.py

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from accounts.models import User

from .models import Period, TimetableEntry


class SchoolIsolationMixin:
    """Makes the school field read-only for non-superusers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        user = getattr(request, "user", None)

        if (
            user
            and user.is_authenticated
            and not user.is_superuser
            and "school" in self.fields
        ):
            self.fields["school"].read_only = True

    def get_request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_effective_school(self, attrs):
        user = self.get_request_user()

        school = attrs.get(
            "school",
            getattr(self.instance, "school", None),
        )

        if (
            school is None
            and user
            and user.is_authenticated
            and not user.is_superuser
        ):
            school = getattr(user, "school", None)

        return school

    @staticmethod
    def convert_django_validation_error(exc):
        if hasattr(exc, "message_dict"):
            raise serializers.ValidationError(exc.message_dict)

        if hasattr(exc, "messages"):
            raise serializers.ValidationError(
                {"non_field_errors": exc.messages}
            )

        raise serializers.ValidationError(str(exc))


class PeriodSerializer(
    SchoolIsolationMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = Period
        fields = [
            "id",
            "school",
            "name",
            "start_time",
            "end_time",
            "order",
            "is_break",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Period name cannot be blank."
            )

        return value

    def validate_order(self, value):
        if value < 1:
            raise serializers.ValidationError(
                "Order must be a positive integer."
            )

        return value

    def validate(self, attrs):
        errors = {}

        school = self.get_effective_school(attrs)

        start_time = attrs.get(
            "start_time",
            getattr(self.instance, "start_time", None),
        )
        end_time = attrs.get(
            "end_time",
            getattr(self.instance, "end_time", None),
        )
        name = attrs.get(
            "name",
            getattr(self.instance, "name", None),
        )
        order = attrs.get(
            "order",
            getattr(self.instance, "order", None),
        )
        is_active = attrs.get(
            "is_active",
            getattr(self.instance, "is_active", True),
        )

        user = self.get_request_user()

        if (
            user
            and user.is_authenticated
            and not user.is_superuser
            and not getattr(user, "school_id", None)
        ):
            errors["school"] = (
                "Your account is not assigned to a school."
            )

        if not school:
            errors["school"] = "A school is required."

        if (
            start_time
            and end_time
            and start_time >= end_time
        ):
            errors["end_time"] = (
                "End time must be after start time."
            )

        if school and name:
            same_name = Period.objects.filter(
                school=school,
                name__iexact=name.strip(),
            )

            if self.instance:
                same_name = same_name.exclude(
                    pk=self.instance.pk,
                )

            if same_name.exists():
                errors["name"] = (
                    "A period with this name already exists "
                    "in this school."
                )

        if school and order is not None:
            same_order = Period.objects.filter(
                school=school,
                order=order,
            )

            if self.instance:
                same_order = same_order.exclude(
                    pk=self.instance.pk,
                )

            if same_order.exists():
                errors["order"] = (
                    "A period with this order already exists "
                    "in this school."
                )

        valid_time_range = (
            start_time
            and end_time
            and start_time < end_time
        )

        if (
            is_active
            and school
            and valid_time_range
        ):
            overlapping = Period.objects.filter(
                school=school,
                is_active=True,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )

            if self.instance:
                overlapping = overlapping.exclude(
                    pk=self.instance.pk,
                )

            other = overlapping.first()

            if other:
                errors["start_time"] = (
                    f"This period overlaps with '{other.name}' "
                    f"({other.start_time}-{other.end_time})."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                return super().create(validated_data)

        except DjangoValidationError as exc:
            self.convert_django_validation_error(exc)

        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "A period with the same name or order "
                        "already exists in this school."
                    ]
                }
            )

    def update(self, instance, validated_data):
        try:
            with transaction.atomic():
                return super().update(
                    instance,
                    validated_data,
                )

        except DjangoValidationError as exc:
            self.convert_django_validation_error(exc)

        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "This update conflicts with an existing "
                        "period in the school."
                    ]
                }
            )


class TimetableEntrySerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(
        source="classroom_subject.subject.name",
        read_only=True,
    )
    classroom_name = serializers.CharField(
        source="classroom_subject.classroom.name",
        read_only=True,
    )
    teacher_name = serializers.SerializerMethodField()
    academic_term_name = serializers.CharField(
        source="classroom_subject.academic_term.name",
        read_only=True,
    )
    period_name = serializers.CharField(
        source="period.name",
        read_only=True,
    )
    start_time = serializers.TimeField(
        source="period.start_time",
        read_only=True,
    )
    end_time = serializers.TimeField(
        source="period.end_time",
        read_only=True,
    )

    class Meta:
        model = TimetableEntry
        fields = [
            "id",
            "school",
            "classroom_subject",
            "period",
            "weekday",
            "room",
            "notes",
            "is_active",
            "subject_name",
            "classroom_name",
            "teacher_name",
            "academic_term_name",
            "period_name",
            "start_time",
            "end_time",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "created_at",
            "updated_at",
        ]

    def get_teacher_name(self, obj):
        teacher = obj.classroom_subject.teacher

        if not teacher:
            return None

        full_name = teacher.get_full_name()

        return full_name or str(teacher)

    def get_request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    @staticmethod
    def convert_django_validation_error(exc):
        if hasattr(exc, "message_dict"):
            raise serializers.ValidationError(exc.message_dict)

        if hasattr(exc, "messages"):
            raise serializers.ValidationError(
                {"non_field_errors": exc.messages}
            )

        raise serializers.ValidationError(str(exc))

    def validate(self, attrs):
        user = self.get_request_user()
        errors = {}

        classroom_subject = attrs.get(
            "classroom_subject",
            getattr(
                self.instance,
                "classroom_subject",
                None,
            ),
        )
        period = attrs.get(
            "period",
            getattr(self.instance, "period", None),
        )
        weekday = attrs.get(
            "weekday",
            getattr(self.instance, "weekday", None),
        )
        room = attrs.get(
            "room",
            getattr(self.instance, "room", ""),
        )
        notes = attrs.get(
            "notes",
            getattr(self.instance, "notes", ""),
        )
        is_active = attrs.get(
            "is_active",
            getattr(self.instance, "is_active", True),
        )

        room = room.strip() if room else ""
        notes = notes.strip() if notes else ""

        attrs["room"] = room
        attrs["notes"] = notes

        if not classroom_subject:
            errors["classroom_subject"] = (
                "This field is required."
            )

        if not period:
            errors["period"] = "This field is required."

        if errors:
            raise serializers.ValidationError(errors)

        school = classroom_subject.school

        if (
            user
            and user.is_authenticated
            and not user.is_superuser
        ):
            if not getattr(user, "school_id", None):
                errors["school"] = (
                    "Your account is not assigned to a school."
                )
            elif classroom_subject.school_id != user.school_id:
                errors["classroom_subject"] = (
                    "The classroom subject must belong to "
                    "your own school."
                )

        if period.school_id != classroom_subject.school_id:
            errors["period"] = (
                "The period must belong to the same school "
                "as the classroom subject."
            )

        if not classroom_subject.is_active:
            errors["classroom_subject"] = (
                "The classroom subject must be active."
            )

        if not period.is_active:
            errors["period"] = "The period must be active."

        elif period.is_break:
            errors["period"] = (
                "Break periods cannot be used for lessons."
            )

        teacher = classroom_subject.teacher

        if teacher:
            if not teacher.is_active:
                errors["classroom_subject"] = (
                    "The assigned teacher must be active."
                )

            elif (
                teacher.approval_status
                != User.ApprovalStatus.APPROVED
            ):
                errors["classroom_subject"] = (
                    "The assigned teacher must be approved."
                )

            elif (
                teacher.school_id
                != classroom_subject.school_id
            ):
                errors["classroom_subject"] = (
                    "The assigned teacher must belong to "
                    "the same school."
                )

        if (
            not errors
            and is_active
            and weekday
            and period
        ):
            conflict_qs = TimetableEntry.objects.filter(
                school_id=school.id,
                weekday=weekday,
                period=period,
                is_active=True,
            )

            if self.instance:
                conflict_qs = conflict_qs.exclude(
                    pk=self.instance.pk,
                )

            duplicate = conflict_qs.filter(
                classroom_subject=classroom_subject,
            ).exists()

            if duplicate:
                errors["classroom_subject"] = (
                    "This exact lesson is already scheduled "
                    "for this weekday and period."
                )

            classroom_conflict = conflict_qs.filter(
                classroom_subject__classroom_id=(
                    classroom_subject.classroom_id
                ),
            ).exists()

            if classroom_conflict:
                errors.setdefault(
                    "period",
                    "This classroom already has a lesson "
                    "scheduled during this weekday and period.",
                )

            if teacher:
                teacher_conflict = conflict_qs.filter(
                    classroom_subject__teacher_id=teacher.id,
                ).exists()

                if teacher_conflict:
                    errors.setdefault(
                        "classroom_subject",
                        "This teacher already has a lesson "
                        "scheduled during this weekday and period.",
                    )

            if room:
                room_conflict = conflict_qs.filter(
                    room__iexact=room,
                ).exists()

                if room_conflict:
                    errors["room"] = (
                        "This room is already booked during "
                        "this weekday and period."
                    )

        if errors:
            raise serializers.ValidationError(errors)

        attrs["school"] = school

        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                return super().create(validated_data)

        except DjangoValidationError as exc:
            self.convert_django_validation_error(exc)

        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "This timetable entry conflicts with "
                        "an existing active timetable entry."
                    ]
                }
            )

    def update(self, instance, validated_data):
        try:
            with transaction.atomic():
                return super().update(
                    instance,
                    validated_data,
                )

        except DjangoValidationError as exc:
            self.convert_django_validation_error(exc)

        except IntegrityError:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "This update conflicts with an existing "
                        "active timetable entry."
                    ]
                }
            )