from django.contrib import admin
from .models import (
    ClassRepresentativeAssignment,
    Announcement,
    GroupSet,
    StudyGroup,
    GroupMember,
    Poll,
    PollOption,
    PollVote,
    StudentFeedback,
    AuditLog,
)

@admin.register(ClassRepresentativeAssignment)
class ClassRepresentativeAssignmentAdmin(admin.ModelAdmin):
    list_display = ("student", "classroom", "is_active", "assigned_by", "created_at")
    list_filter = ("is_active", "can_publish_notices", "can_manage_materials", "can_create_study_groups")
    search_fields = ("student__email", "student__first_name", "student__last_name", "classroom__name")

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "status", "priority", "created_by", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "classroom__name")

@admin.register(GroupSet)
class GroupSetAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "classroom", "status", "allocation_method", "created_at")
    list_filter = ("status", "allocation_method")
    search_fields = ("title", "subject__name")

@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "group_set", "leader", "created_at")
    search_fields = ("name", "group_set__title")

@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = ("group", "student", "is_leader", "joined_at")
    search_fields = ("student__email", "group__name")

@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "status", "is_anonymous", "deadline", "created_at")
    list_filter = ("status", "is_anonymous")
    search_fields = ("title", "classroom__name")

@admin.register(PollOption)
class PollOptionAdmin(admin.ModelAdmin):
    list_display = ("poll", "text")
    search_fields = ("text", "poll__title")

@admin.register(PollVote)
class PollVoteAdmin(admin.ModelAdmin):
    list_display = ("poll", "option", "voted_at")
    search_fields = ("poll__title",)

@admin.register(StudentFeedback)
class StudentFeedbackAdmin(admin.ModelAdmin):
    list_display = ("subject_line", "classroom", "category", "priority", "status", "is_anonymous", "created_at")
    list_filter = ("category", "priority", "status", "is_anonymous")
    search_fields = ("subject_line", "content")

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action_type", "actor", "target_model", "target_id", "timestamp")
    list_filter = ("action_type", "target_model")
    search_fields = ("actor__email", "description")
