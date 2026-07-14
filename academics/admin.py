from django.contrib import admin

from .models import Classroom


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "level",
        "school",
        "is_active",
    )

    list_filter = (
        "school",
        "level",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "school__name",
    )