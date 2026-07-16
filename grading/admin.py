# grading/admin.py

from django.contrib import admin

from .models import (
    Assessment,
    AssessmentType,
    Grade,
    GradeHistory,
    SubjectGradeApproval,
)


@admin.register(AssessmentType)
class AssessmentTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "school",
        "weight_percentage",
        "is_active",
        "created_at",
    )

    list_filter = (
        "school",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "school__name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "classroom_subject",
        "assessment_type",
        "maximum_score",
        "assessment_date",
        "school",
        "is_active",
    )

    list_filter = (
        "school",
        "assessment_type",
        "assessment_date",
        "is_active",
    )

    search_fields = (
        "title",
        "classroom_subject__subject__name",
        "classroom_subject__classroom__name",
        "assessment_type__name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "classroom_subject",
        "assessment_type",
    )


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = (
        "student_enrollment",
        "assessment",
        "score",
        "assessment_maximum_score",
        "percentage",
        "status",
        "recorded_by",
        "school",
    )

    list_filter = (
        "school",
        "status",
        "assessment__assessment_type",
        "assessment__classroom_subject",
    )

    search_fields = (
        "student_enrollment__student__student_id_number",
        "student_enrollment__student__user__email",
        "student_enrollment__student__user__first_name",
        "student_enrollment__student__user__last_name",
        "assessment__title",
        "remarks",
    )

    readonly_fields = (
        "percentage",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "student_enrollment",
        "assessment",
        "recorded_by",
    )

    def assessment_maximum_score(self, obj):
        return obj.assessment.maximum_score

    assessment_maximum_score.short_description = "Maximum score"


@admin.register(GradeHistory)
class GradeHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "grade",
        "changed_by",
        "old_score",
        "new_score",
        "old_status",
        "new_status",
        "changed_at",
    )

    list_filter = (
        "old_status",
        "new_status",
        "changed_at",
    )

    search_fields = (
        "grade__student_enrollment__student__student_id_number",
        "grade__student_enrollment__student__user__email",
        "grade__assessment__title",
        "reason",
    )

    readonly_fields = (
        "grade",
        "changed_by",
        "old_score",
        "new_score",
        "old_status",
        "new_status",
        "reason",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SubjectGradeApproval)
class SubjectGradeApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "classroom_subject",
        "school",
        "status",
        "approved_by",
        "approved_at",
    )

    list_filter = (
        "school",
        "status",
    )

    search_fields = (
        "classroom_subject__subject__name",
        "classroom_subject__classroom__name",
        "approved_by__email",
    )

    readonly_fields = (
        "approved_by",
        "approved_at",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "classroom_subject",
    )