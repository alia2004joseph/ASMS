# academics/serializers.py

from rest_framework import serializers

from accounts.models import User
from .models import (
    AcademicTerm,
    AcademicYear,
    Classroom,
    ClassroomSubject,
    StudentEnrollment,
    Subject,
)


class SchoolIsolationMixin:
    """
    Makes the school field read-only for non-superusers.

    The corresponding view must assign request.user.school during creation.
    """

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


class AcademicYearSerializer(
    SchoolIsolationMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = AcademicYear
        fields = [
            "id",
            "school",
            "name",
            "start_date",
            "end_date",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


class AcademicTermSerializer(
    SchoolIsolationMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = AcademicTerm
        fields = [
            "id",
            "school",
            "academic_year",
            "name",
            "start_date",
            "end_date",
            "is_active",
            "subject_change_deadline",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        user = self.get_request_user()

        academic_year = attrs.get(
            "academic_year",
            getattr(self.instance, "academic_year", None),
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

        if (
            academic_year
            and school
            and academic_year.school_id != school.id
        ):
            raise serializers.ValidationError(
                {
                    "academic_year": (
                        "The academic year must belong to the same school."
                    )
                }
            )

        return attrs


class ClassroomSerializer(
    SchoolIsolationMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = Classroom
        fields = [
            "id",
            "school",
            "academic_year",
            "name",
            "code",
            "level",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
    "id",
    "school",
    "created_at",
    "updated_at",
]

    def validate(self, attrs):
        user = self.get_request_user()

        academic_year = attrs.get(
            "academic_year",
            getattr(self.instance, "academic_year", None),
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

        if (
            academic_year
            and school
            and academic_year.school_id != school.id
        ):
            raise serializers.ValidationError(
                {
                    "academic_year": (
                        "The academic year must belong to the classroom's "
                        "school."
                    )
                }
            )

        return attrs


class SubjectSerializer(
    SchoolIsolationMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = Subject
        fields = [
            "id",
            "school",
            "name",
            "code",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


class ClassroomSubjectSerializer(
    SchoolIsolationMixin,
    serializers.ModelSerializer,
):
    teacher = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            role=User.Role.TEACHER,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True,
        ),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ClassroomSubject
        fields = [
            "id",
            "school",
            "classroom",
            "subject",
            "academic_term",
            "teacher",
            "is_compulsory",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        user = self.get_request_user()

        classroom = attrs.get(
            "classroom",
            getattr(self.instance, "classroom", None),
        )

        subject = attrs.get(
            "subject",
            getattr(self.instance, "subject", None),
        )

        academic_term = attrs.get(
            "academic_term",
            getattr(self.instance, "academic_term", None),
        )

        teacher = attrs.get(
            "teacher",
            getattr(self.instance, "teacher", None),
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

        if school is None and classroom:
            school = classroom.school

        errors = {}

        if classroom and school and classroom.school_id != school.id:
            errors["classroom"] = (
                "The classroom must belong to the selected school."
            )

        if subject and school and subject.school_id != school.id:
            errors["subject"] = (
                "The subject must belong to the selected school."
            )

        if (
            academic_term
            and school
            and academic_term.school_id != school.id
        ):
            errors["academic_term"] = (
                "The academic term must belong to the selected school."
            )

        if classroom and academic_term:
            if (
                classroom.academic_year_id
                and classroom.academic_year_id
                != academic_term.academic_year_id
            ):
                errors["academic_term"] = (
                    "The academic term must belong to the classroom's "
                    "academic year."
                )

        if teacher:
            if teacher.role != User.Role.TEACHER:
                errors["teacher"] = (
                    "The selected user must be a teacher."
                )
            elif not teacher.is_active:
                errors["teacher"] = (
                    "The selected teacher must be active."
                )
            elif (
                teacher.approval_status
                != User.ApprovalStatus.APPROVED
            ):
                errors["teacher"] = (
                    "The selected teacher must be approved."
                )
            elif school and teacher.school_id != school.id:
                errors["teacher"] = (
                    "The teacher must belong to the same school."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class StudentEnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentEnrollment
        fields = [
            "id",
            "student",
            "classroom_subject",
            "enrolled_at",
            "is_active",
        ]
        read_only_fields = [
            "id",
            "enrolled_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        request_user = getattr(request, "user", None)

        student = attrs.get(
            "student",
            getattr(self.instance, "student", None),
        )

        classroom_subject = attrs.get(
            "classroom_subject",
            getattr(self.instance, "classroom_subject", None),
        )

        errors = {}

        if student and classroom_subject:
            school = classroom_subject.school

            if (
                request_user
                and request_user.is_authenticated
                and not request_user.is_superuser
                and request_user.school_id != school.id
            ):
                raise serializers.ValidationError(
                    "You may only manage enrollments for your own school."
                )

            if student.school_id != school.id:
                errors["student"] = (
                    "The student and classroom subject must belong "
                    "to the same school."
                )

            if student.classroom_id is None:
                errors["student"] = (
                    "Assign the student to a classroom before enrolling "
                    "them in a subject."
                )
            elif (
                student.classroom_id
                != classroom_subject.classroom_id
            ):
                errors["classroom_subject"] = (
                    "The classroom subject must belong to the student's "
                    "current classroom."
                )

            if not student.is_active_student:
                errors["student"] = (
                    "An inactive student cannot be enrolled."
                )

            if not student.user.is_active:
                errors["student"] = (
                    "The student's account must be active."
                )
            elif (
                student.user.approval_status
                != User.ApprovalStatus.APPROVED
            ):
                errors["student"] = (
                    "The student's account must be approved."
                )

            if not classroom_subject.is_active:
                errors["classroom_subject"] = (
                    "The classroom subject must be active."
                )

            duplicate_query = StudentEnrollment.objects.filter(
                student=student,
                classroom_subject=classroom_subject,
            )

            if self.instance:
                duplicate_query = duplicate_query.exclude(
                    pk=self.instance.pk
                )

            if duplicate_query.exists():
                errors["classroom_subject"] = (
                    "This student is already enrolled in this subject."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs