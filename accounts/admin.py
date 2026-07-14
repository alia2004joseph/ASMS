# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    AccessCode,
    GuardianStudentLink,
    StudentProfile,
    User,
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = (
        "email",
        "first_name",
        "last_name",
        "role",
        "school",
        "approval_status",
        "is_active",
        "is_staff",
    )
    list_filter = (
        "role",
        "approval_status",
        "school",
        "is_active",
        "is_staff",
    )
    search_fields = (
        "email",
        "first_name",
        "last_name",
    )
    ordering = ("email",)

    # These are managed by User.approve()/User.reject() so that approving
    # or rejecting an account always keeps approval_status, approved_by,
    # approved_at, and is_active in sync. Leaving them editable would let
    # staff flip approval_status in the change form without is_active or
    # the audit fields ever being updated (see save_model below, which
    # calls approve()/reject() when approval_status changes).
    readonly_fields = (
        "approved_by",
        "approved_at",
    )

    actions = ["approve_users"]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "email",
                    "password",
                )
            },
        ),
        (
            "Personal information",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "profile_picture",
                    "school",
                    "role",
                )
            },
        ),
        (
            "Account approval",
            {
                "fields": (
                    "approval_status",
                    "approved_by",
                    "approved_at",
                    "rejection_reason",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important dates",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                )
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "school",
                    "role",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        """
        Route approval-status changes through User.approve()/User.reject()
        instead of letting the plain form save leave is_active and the
        audit fields (approved_by/approved_at) out of sync with
        approval_status.
        """

        if change and "approval_status" in form.changed_data:
            if obj.approval_status == User.ApprovalStatus.APPROVED:
                # Re-fetch the pre-save state so approve() runs against a
                # persisted instance, then reapply any other edited fields.
                original = User.objects.get(pk=obj.pk)
                for field in form.changed_data:
                    if field not in ("approval_status", "approved_by", "approved_at"):
                        setattr(original, field, getattr(obj, field))
                original.approve(approved_by=request.user)
                return

            if obj.approval_status == User.ApprovalStatus.REJECTED:
                original = User.objects.get(pk=obj.pk)
                for field in form.changed_data:
                    if field not in (
                        "approval_status",
                        "approved_by",
                        "approved_at",
                        "is_active",
                    ):
                        setattr(original, field, getattr(obj, field))
                try:
                    original.reject(
                        approved_by=request.user,
                        reason=obj.rejection_reason,
                    )
                except ValidationError as exc:
                    self.message_user(request, str(exc), level="ERROR")
                    return
                return

        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected users")
    def approve_users(self, request, queryset):
        approved_count = 0

        for user in queryset:
            if user.is_approved:
                continue

            try:
                user.approve(approved_by=request.user)
                approved_count += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"Could not approve {user}: {exc}",
                    level="ERROR",
                )

        if approved_count:
            self.message_user(
                request,
                f"Approved {approved_count} user(s).",
            )


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = (
        "student_id_number",
        "user",
        "school",
        "classroom",
        "is_active_student",
    )
    list_filter = (
        "school",
        "classroom",
        "is_active_student",
    )
    search_fields = (
        "student_id_number",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    autocomplete_fields = ("user", "classroom")


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "school",
        "role",
        "times_used",
        "max_uses",
        "expires_at",
        "is_active",
    )
    list_filter = (
        "school",
        "role",
        "is_active",
    )
    search_fields = ("code",)
    # code is editable=False on the model, so Django already excludes it
    # from the form automatically; times_used is bumped only through
    # AccessCode.consume() and shouldn't be hand-edited from the admin.
    readonly_fields = ("times_used",)


@admin.register(GuardianStudentLink)
class GuardianStudentLinkAdmin(admin.ModelAdmin):
    list_display = (
        "guardian",
        "student",
        "relationship",
        "is_primary_guardian",
        "can_receive_notifications",
    )
    list_filter = (
        "is_primary_guardian",
        "can_receive_notifications",
    )
    search_fields = (
        "guardian__email",
        "student__email",
        "student__first_name",
        "student__last_name",
    )
    autocomplete_fields = ("guardian", "student")