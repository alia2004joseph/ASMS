# attendance/admin.py

from django.contrib import admin

from .models import AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "student_display",
        "classroom_display",
        "subject_display",
        "teacher_display",
        "status",
        "marked_by_display",
        "school",
        "is_active",
    ]

    list_filter = [
        "school",
        "status",
        "is_active",
        "date",
        "timetable_entry__weekday",
        "timetable_entry__classroom_subject__classroom",
        "timetable_entry__classroom_subject__subject",
    ]

    search_fields = [
        "student__user__first_name",
        "student__user__last_name",
        "student__user__email",
        "student__student_number",
        "timetable_entry__classroom_subject__classroom__name",
        "timetable_entry__classroom_subject__subject__name",
        "timetable_entry__classroom_subject__teacher__first_name",
        "timetable_entry__classroom_subject__teacher__last_name",
        "marked_by__first_name",
        "marked_by__last_name",
        "remarks",
    ]

    ordering = [
        "-date",
        "timetable_entry__period__order",
        "student__user__last_name",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    autocomplete_fields = [
        "school",
        "timetable_entry",
        "student",
        "marked_by",
    ]

    list_select_related = [
        "school",
        "student",
        "student__user",
        "timetable_entry",
        "timetable_entry__period",
        "timetable_entry__classroom_subject",
        "timetable_entry__classroom_subject__classroom",
        "timetable_entry__classroom_subject__subject",
        "timetable_entry__classroom_subject__teacher",
        "marked_by",
    ]

    date_hierarchy = "date"
    list_per_page = 50
    save_on_top = True

    fieldsets = (
        (
            "Attendance Details",
            {
                "fields": (
                    "school",
                    "timetable_entry",
                    "student",
                    "date",
                    "status",
                    "remarks",
                    "is_active",
                )
            },
        ),
        (
            "Record Information",
            {
                "fields": (
                    "marked_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(
        description="Student",
        ordering="student__user__last_name",
    )
    def student_display(self, obj):
        user = obj.student.user
        full_name = user.get_full_name()
        return full_name or str(obj.student)

    @admin.display(
        description="Classroom",
        ordering=(
            "timetable_entry__classroom_subject__classroom__name"
        ),
    )
    def classroom_display(self, obj):
        return (
            obj.timetable_entry
            .classroom_subject
            .classroom
        )

    @admin.display(
        description="Subject",
        ordering=(
            "timetable_entry__classroom_subject__subject__name"
        ),
    )
    def subject_display(self, obj):
        return (
            obj.timetable_entry
            .classroom_subject
            .subject
        )

    @admin.display(
        description="Teacher",
        ordering=(
            "timetable_entry__classroom_subject__teacher__last_name"
        ),
    )
    def teacher_display(self, obj):
        teacher = (
            obj.timetable_entry
            .classroom_subject
            .teacher
        )

        if teacher is None:
            return "Not assigned"

        full_name = teacher.get_full_name()
        return full_name or str(teacher)

    @admin.display(
        description="Marked By",
        ordering="marked_by__last_name",
    )
    def marked_by_display(self, obj):
        if obj.marked_by is None:
            return "Not recorded"

        full_name = obj.marked_by.get_full_name()
        return full_name or str(obj.marked_by)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "school",
            "student",
            "student__user",
            "timetable_entry",
            "timetable_entry__period",
            "timetable_entry__classroom_subject",
            "timetable_entry__classroom_subject__classroom",
            "timetable_entry__classroom_subject__subject",
            "timetable_entry__classroom_subject__teacher",
            "marked_by",
        )