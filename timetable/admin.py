# timetable/admin.py

from django.contrib import admin
from django.db.models import Case, IntegerField, Value, When

from .models import Period, TimetableEntry


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "school",
        "start_time",
        "end_time",
        "order",
        "is_break",
        "is_active",
    ]
    list_filter = [
        "school",
        "is_break",
        "is_active",
    ]
    search_fields = [
        "name",
        "school__name",
    ]
    ordering = [
        "school",
        "order",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = [
        "school",
    ]
    list_select_related = [
        "school",
    ]


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    list_display = [
        "weekday",
        "period",
        "classroom_display",
        "subject_display",
        "teacher_display",
        "room",
        "school",
        "academic_term_display",
        "is_active",
    ]
    list_filter = [
        "school",
        "weekday",
        "period",
        "is_active",
        "classroom_subject__academic_term",
        "classroom_subject__classroom",
        "classroom_subject__teacher",
    ]
    search_fields = [
        "classroom_subject__classroom__name",
        "classroom_subject__classroom__code",
        "classroom_subject__subject__name",
        "classroom_subject__subject__code",
        "classroom_subject__teacher__first_name",
        "classroom_subject__teacher__last_name",
        "classroom_subject__teacher__email",
        "room",
        "school__name",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = [
        "school",
        "classroom_subject",
        "period",
    ]
    list_select_related = [
        "school",
        "period",
        "classroom_subject",
        "classroom_subject__classroom",
        "classroom_subject__subject",
        "classroom_subject__teacher",
        "classroom_subject__academic_term",
    ]

    def get_queryset(self, request):
        weekday_order = Case(
            When(
                weekday=TimetableEntry.Weekday.MONDAY,
                then=Value(1),
            ),
            When(
                weekday=TimetableEntry.Weekday.TUESDAY,
                then=Value(2),
            ),
            When(
                weekday=TimetableEntry.Weekday.WEDNESDAY,
                then=Value(3),
            ),
            When(
                weekday=TimetableEntry.Weekday.THURSDAY,
                then=Value(4),
            ),
            When(
                weekday=TimetableEntry.Weekday.FRIDAY,
                then=Value(5),
            ),
            When(
                weekday=TimetableEntry.Weekday.SATURDAY,
                then=Value(6),
            ),
            When(
                weekday=TimetableEntry.Weekday.SUNDAY,
                then=Value(7),
            ),
            output_field=IntegerField(),
        )

        return (
            super()
            .get_queryset(request)
            .annotate(weekday_order=weekday_order)
            .order_by(
                "school_id",
                "weekday_order",
                "period__order",
            )
        )

    @admin.display(
        description="Classroom",
        ordering="classroom_subject__classroom__name",
    )
    def classroom_display(self, obj):
        return obj.classroom_subject.classroom

    @admin.display(
        description="Subject",
        ordering="classroom_subject__subject__name",
    )
    def subject_display(self, obj):
        return obj.classroom_subject.subject

    @admin.display(
        description="Teacher",
        ordering="classroom_subject__teacher__first_name",
    )
    def teacher_display(self, obj):
        teacher = obj.classroom_subject.teacher

        if teacher is None:
            return "Unassigned"

        full_name = teacher.get_full_name()
        return full_name or str(teacher)

    @admin.display(
        description="Academic Term",
        ordering="classroom_subject__academic_term__start_date",
    )
    def academic_term_display(self, obj):
        return obj.classroom_subject.academic_term