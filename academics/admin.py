from django.contrib import admin

from .models import (
    AcademicYear,
    AcademicTerm,
    Classroom,
    Subject,
    ClassroomSubject,
    StudentEnrollment,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "school",
        "start_date",
        "end_date",
        "is_active",
    )
    list_filter = (
        "school",
        "is_active",
    )
    search_fields = (
        "name",
        "school__name",
    )


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "academic_year",
        "school",
        "start_date",
        "end_date",
        "is_active",
    )
    list_filter = (
        "school",
        "academic_year",
        "is_active",
    )
    search_fields = (
        "academic_year__name",
        "school__name",
    )


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "school",
        "academic_year",
        "level",
        "is_active",
    )
    list_filter = (
        "school",
        "academic_year",
        "level",
        "is_active",
    )
    search_fields = (
        "name",
        "code",
    )


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "school",
        "is_active",
    )
    list_filter = (
        "school",
        "is_active",
    )
    search_fields = (
        "name",
        "code",
    )


@admin.register(ClassroomSubject)
class ClassroomSubjectAdmin(admin.ModelAdmin):
    list_display = (
        "classroom",
        "subject",
        "academic_term",
        "teacher",
        "is_compulsory",
        "is_active",
    )
    list_filter = (
        "academic_term",
        "is_compulsory",
        "is_active",
    )
    search_fields = (
        "classroom__name",
        "subject__name",
    )


@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "classroom_subject",
        "is_active",
        "enrolled_at",
    )
    list_filter = (
        "is_active",
    )
    search_fields = (
        "student__student_id_number",
        "student__user__first_name",
        "student__user__last_name",
    )