from django.contrib import admin
from .models import (
    ClassRepresentativeAssignment,
    ClassMaterial,
    ClassAnnouncement,
    ClassGroupSet,
    ClassGroup,
    ClassGroupMembership,
    ClassAttendanceSession,
    ClassAttendanceEntry,
    ClassPoll,
    ClassPollOption,
    ClassPollVote,
    ClassStudentFeedback,
    ClassAuditLog,
)

@admin.register(ClassRepresentativeAssignment)
class ClassRepresentativeAssignmentAdmin(admin.ModelAdmin):
    list_display = ("student", "classroom", "is_active", "assigned_by", "created_at")
    list_filter = ("is_active", "can_publish_notices", "can_manage_materials", "can_create_study_groups")
    search_fields = ("student__email", "student__first_name", "student__last_name", "classroom__name")

@admin.register(ClassMaterial)
class ClassMaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "classroom", "category", "is_published", "created_at")
    list_filter = ("category", "is_published")
    search_fields = ("title", "subject__name", "classroom__name")

@admin.register(ClassAnnouncement)
class ClassAnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "status", "priority", "created_by", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "classroom__name")

@admin.register(ClassGroupSet)
class ClassGroupSetAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "classroom", "status", "allocation_method", "created_at")
    list_filter = ("status", "allocation_method")
    search_fields = ("title", "subject__name")

@admin.register(ClassAttendanceSession)
class ClassAttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("session_code", "topic", "venue", "is_active", "date", "created_at")
    list_filter = ("is_active", "date")
    search_fields = ("session_code", "topic", "venue")

@admin.register(ClassPoll)
class ClassPollAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "status", "is_anonymous", "deadline", "created_at")
    list_filter = ("status", "is_anonymous")
    search_fields = ("title", "classroom__name")

@admin.register(ClassStudentFeedback)
class ClassStudentFeedbackAdmin(admin.ModelAdmin):
    list_display = ("subject_line", "classroom", "category", "priority", "status", "is_anonymous", "created_at")
    list_filter = ("category", "priority", "status", "is_anonymous")
    search_fields = ("subject_line", "content")

@admin.register(ClassAuditLog)
class ClassAuditLogAdmin(admin.ModelAdmin):
    list_display = ("action_type", "actor", "target_model", "target_id", "timestamp")
    list_filter = ("action_type", "target_model")
    search_fields = ("actor__email", "description")
