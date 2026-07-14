from django.contrib import admin

from .models import School


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "email",
        "phone",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "email",
    )

    list_filter = ("is_active",)