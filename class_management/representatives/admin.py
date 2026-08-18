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
    list_display = ("student", "classroom", "classroom_subject", "academic_term", "status", "appointed_by", "appointed_at")
    list_filter = ("status", "can_manage_materials", "can_manage_attendance", "can_create_announcements", "can_create_groups", "can_create_polls")
    search_fields = ("student__student_id_number", "student__user__first_name", "student__user__last_name", "classroom__name")

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "status", "priority", "created_by", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "classroom__name")

@admin.register(GroupSet)
class GroupSetAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "classroom_subject", "status", "allocation_method", "num_groups", "created_at")
    list_filter = ("status", "allocation_method")
    search_fields = ("title", "classroom_subject__subject__name", "classroom__name")

@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "group_number", "group_set", "leader_student")
    search_fields = ("name", "group_set__title")

@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = ("study_group", "student", "role", "assigned_at")
    list_filter = ("role",)
    search_fields = ("student__student_id_number", "study_group__name")

@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "poll_type", "status", "is_anonymous", "end_time", "created_at")
    list_filter = ("status", "poll_type", "is_anonymous")
    search_fields = ("title", "classroom__name")

@admin.register(PollOption)
class PollOptionAdmin(admin.ModelAdmin):
    list_display = ("poll", "text", "vote_count")
    search_fields = ("text", "poll__title")

@admin.register(PollVote)
class PollVoteAdmin(admin.ModelAdmin):
    list_display = ("poll", "option", "vote_type", "voted_at")
    search_fields = ("poll__title", "voter_hash")

@admin.register(StudentFeedback)
class StudentFeedbackAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "classroom_subject", "category", "status", "is_anonymous", "created_at")
    list_filter = ("category", "status", "is_anonymous")
    search_fields = ("title", "message")

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user_name", "user_role", "entity_type", "entity_id", "timestamp")
    list_filter = ("action", "entity_type", "user_role")
    search_fields = ("user_name", "details")
