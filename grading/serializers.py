# grading/serializers.py
from rest_framework import serializers
from accounts.models import User

from .models import (
    Assessment,
    AssessmentType,
    Grade,
    GradeHistory,
    SubjectGradeApproval,
)


class AssessmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentType
        fields = [
            "id",
            "school",
            "name",
            "code",
            "weight_percentage",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        user = getattr(request, "user", None)

        if (
            user
            and user.is_authenticated
            and not user.is_superuser
        ):
            self.fields["school"].read_only = True

    def validate_weight_percentage(self, value):
        if value <= 0 or value > 100:
            raise serializers.ValidationError(
                "Weight percentage must be greater than 0 "
                "and at most 100."
            )

        return value

class AssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assessment
        fields = [
            "id",
            "school",
            "classroom_subject",
            "assessment_type",
            "title",
            "maximum_score",
            "assessment_date",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")

        if (
            request
            and request.user.is_authenticated
            and not request.user.is_superuser
        ):
            self.fields["school"].read_only = True

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        classroom_subject = attrs.get(
            "classroom_subject",
            getattr(self.instance, "classroom_subject", None),
        )

        assessment_type = attrs.get(
            "assessment_type",
            getattr(self.instance, "assessment_type", None),
        )

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
            school = user.school

        errors = {}

        if (
            classroom_subject
            and school
            and classroom_subject.school_id != school.id
        ):
            errors["classroom_subject"] = (
                "Classroom subject does not belong to the selected school."
            )

        if (
            assessment_type
            and school
            and assessment_type.school_id != school.id
        ):
            errors["assessment_type"] = (
                "Assessment type does not belong to the selected school."
            )

        if (
            classroom_subject
            and not classroom_subject.is_active
        ):
            errors["classroom_subject"] = (
                "Assessments cannot be created for an inactive "
                "classroom subject."
            )

        if (
            assessment_type
            and not assessment_type.is_active
        ):
            errors["assessment_type"] = (
                "The selected assessment type is inactive."
            )

        maximum_score = attrs.get(
            "maximum_score",
            getattr(self.instance, "maximum_score", None),
        )

        if maximum_score is not None and maximum_score <= 0:
            errors["maximum_score"] = (
                "Maximum score must be greater than zero."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class GradeSerializer(serializers.ModelSerializer):
    percentage = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        read_only=True,
    )

    maximum_score = serializers.DecimalField(
        source="assessment.maximum_score",
        max_digits=6,
        decimal_places=2,
        read_only=True,
    )

    assessment_title = serializers.CharField(
        source="assessment.title",
        read_only=True,
    )

    class Meta:
        model = Grade
        fields = [
            "id",
            "school",
            "student_enrollment",
            "assessment",
            "assessment_title",
            "score",
            "maximum_score",
            "percentage",
            "recorded_by",
            "remarks",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "assessment_title",
            "maximum_score",
            "percentage",
            "recorded_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        student_enrollment = attrs.get(
            "student_enrollment",
            getattr(self.instance, "student_enrollment", None),
        )

        assessment = attrs.get(
            "assessment",
            getattr(self.instance, "assessment", None),
        )

        score = attrs.get(
            "score",
            getattr(self.instance, "score", None),
        )

        errors = {}

        if score is not None and score < 0:
            errors["score"] = "Score cannot be negative."

        if (
            score is not None
            and assessment
            and score > assessment.maximum_score
        ):
            errors["score"] = (
                "Score cannot exceed the assessment maximum score."
            )

        if student_enrollment and assessment:
            if (
                student_enrollment.classroom_subject_id
                != assessment.classroom_subject_id
            ):
                errors["assessment"] = (
                    "The assessment must belong to the same classroom "
                    "subject as the student enrollment."
                )

            if (
                student_enrollment.classroom_subject.school_id
                != assessment.school_id
            ):
                errors["assessment"] = (
                    "The assessment and enrollment must belong "
                    "to the same school."
                )

        if (
            user
            and user.is_authenticated
            and not user.is_superuser
        ):
            if user.role != User.Role.TEACHER:
                errors["recorded_by"] = (
                    "Only teachers may record grades."
                )
            elif (
                student_enrollment
                and student_enrollment.classroom_subject.teacher_id
                != user.id
            ):
                errors["student_enrollment"] = (
                    "You are not assigned to this classroom subject."
                )

        duplicate_query = Grade.objects.none()

        if student_enrollment and assessment:
            duplicate_query = Grade.objects.filter(
                student_enrollment=student_enrollment,
                assessment=assessment,
            )

            if self.instance:
                duplicate_query = duplicate_query.exclude(
                    pk=self.instance.pk,
                )

            if duplicate_query.exists():
                errors["assessment"] = (
                    "A grade already exists for this student "
                    "and assessment."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user

        validated_data["recorded_by"] = user
        validated_data["school"] = user.school

        return super().create(validated_data)

    def update(self, instance, validated_data):
        old_score = instance.score
        old_status = instance.status

        grade = super().update(
            instance,
            validated_data,
        )

        request = self.context.get("request")
        user = request.user

        if (
            old_score != grade.score
            or old_status != grade.status
        ):
            GradeHistory.objects.create(
                grade=grade,
                changed_by=user,
                old_score=old_score,
                new_score=grade.score,
                old_status=old_status,
                new_status=grade.status,
                reason=validated_data.get(
                    "remarks",
                    "Grade updated.",
                ),
            )

        return grade

class GradeHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeHistory
        fields = [
            "id", "grade", "changed_by", "old_score", "new_score",
            "old_status", "new_status", "reason", "changed_at",
        ]
        read_only_fields = fields  # fully read-only


class SubjectGradeApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectGradeApproval
        fields = [
            "id",
            "school",
            "classroom_subject",
            "approved_by",
            "status",
            "remarks",
            "approved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "approved_by",
            "status",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        classroom_subject = attrs.get(
            "classroom_subject",
            getattr(self.instance, "classroom_subject", None),
        )

        if (
            classroom_subject
            and user
            and user.is_authenticated
            and not user.is_superuser
            and classroom_subject.school_id != user.school_id
        ):
            raise serializers.ValidationError(
                {
                    "classroom_subject": (
                        "Classroom subject does not belong "
                        "to your school."
                    )
                }
            )

        if (
            classroom_subject
            and user
            and user.role == User.Role.TEACHER
            and classroom_subject.teacher_id != user.id
        ):
            raise serializers.ValidationError(
                {
                    "classroom_subject": (
                        "You may only submit grades for subjects "
                        "assigned to you."
                    )
                }
            )

        return attrs