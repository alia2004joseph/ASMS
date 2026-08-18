from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# ASMS Core Architecture: Integrated Class Management System
# Extends: schoolsys (Django 5.1 / JWT Auth / accounts.User)
# ---------------------------------------------------------------------------

class ClassRepresentativeAssignment(models.Model):
    """
    Official student representative appointment for an ASMS classroom or classroom-subject.
    Maintains accounts.User as single source of truth without duplicating identity tables.
    """
    STATUS_CHOICES = [
        ('ACTIVE', 'Active Representative'),
        ('REVOKED', 'Revoked / Terminated'),
    ]

    school = models.ForeignKey(
        'schools.School',
        on_delete=models.CASCADE,
        related_name='class_representatives'
    )
    student = models.ForeignKey(
        'accounts.StudentProfile',
        on_delete=models.CASCADE,
        related_name='representative_appointments'
    )
    classroom = models.ForeignKey(
        'academics.Classroom',
        on_delete=models.CASCADE,
        related_name='representatives'
    )
    classroom_subject = models.ForeignKey(
        'academics.ClassroomSubject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subject_representatives',
        help_text="Leave empty if General Stream Rep; set if Subject Course Rep."
    )
    academic_term = models.ForeignKey(
        'academics.AcademicTerm',
        on_delete=models.CASCADE,
        related_name='representative_appointments'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    appointed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointed_class_reps'
    )
    appointed_at = models.DateTimeField(auto_now_add=True)

    # Permission Flags
    can_manage_materials = models.BooleanField(default=True)
    can_manage_attendance = models.BooleanField(default=True)
    can_create_announcements = models.BooleanField(default=True)
    can_create_groups = models.BooleanField(default=True)
    can_create_polls = models.BooleanField(default=True)

    class Meta:
        db_table = 'asms_class_rep_assignments'
        ordering = ['-appointed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'classroom', 'classroom_subject', 'academic_term'],
                name='unique_rep_per_scope_and_term'
            )
        ]

    def clean(self):
        if self.student and self.classroom:
            if self.student.classroom_id != self.classroom_id:
                raise ValidationError("The representative must be a registered member of the classroom.")

    def __str__(self):
        scope = self.classroom_subject.subject.name if self.classroom_subject else "General Rep"
        return f"{self.student.user.get_full_name()} — {self.classroom.name} ({scope})"


class Announcement(models.Model):
    """
    Controlled broadcasting noticeboard.
    - Teachers & School Admins publish immediately.
    - Class Rep drafts enter PENDING_REVIEW and require teacher approval.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_REVIEW', 'Pending Teacher Approval'),
        ('PUBLISHED', 'Published & Broadcasted'),
        ('REJECTED', 'Rejected'),
    ]
    PRIORITY_CHOICES = [
        ('NORMAL', 'Normal Notice'),
        ('IMPORTANT', 'Important'),
        ('URGENT', 'Urgent Broadcast'),
    ]

    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, related_name='announcements')
    classroom = models.ForeignKey('academics.Classroom', on_delete=models.CASCADE, related_name='announcements')
    classroom_subject = models.ForeignKey(
        'academics.ClassroomSubject',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='announcements'
    )
    
    title = models.CharField(max_length=255)
    content = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='NORMAL')
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_announcements')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_announcements'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    
    attachment = models.FileField(upload_to='announcements/attachments/', null=True, blank=True)
    attachment_name = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'asms_announcements'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.status}] {self.title} ({self.classroom.name})"


class GroupSet(models.Model):
    """
    Study group container for project teams, laboratory squads, or revision pods.
    """
    ALLOCATION_METHODS = [
        ('RANDOM', 'Random Shuffle'),
        ('BALANCED', 'Balanced Mix (Academic Performance & Skills)'),
        ('MANUAL', 'Manual Rep / Teacher Allocation'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'Draft (Work in Progress)'),
        ('PUBLISHED', 'Published to Students'),
    ]

    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, related_name='group_sets')
    classroom = models.ForeignKey('academics.Classroom', on_delete=models.CASCADE, related_name='group_sets')
    classroom_subject = models.ForeignKey(
        'academics.ClassroomSubject',
        on_delete=models.CASCADE,
        related_name='group_sets'
    )
    
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    
    num_groups = models.PositiveIntegerField(default=4)
    max_members_per_group = models.PositiveIntegerField(default=6)
    allocation_method = models.CharField(max_length=20, choices=ALLOCATION_METHODS, default='BALANCED')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'asms_group_sets'

    def __str__(self):
        return f"{self.title} — {self.classroom_subject.subject.name} ({self.status})"


class StudyGroup(models.Model):
    group_set = models.ForeignKey(GroupSet, on_delete=models.CASCADE, related_name='groups')
    group_number = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    leader_student = models.ForeignKey(
        'accounts.StudentProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='led_study_groups'
    )

    class Meta:
        db_table = 'asms_study_groups'
        unique_together = ('group_set', 'group_number')

    def __str__(self):
        return f"{self.group_set.title} - {self.name}"


class GroupMember(models.Model):
    study_group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='memberships')
    student = models.ForeignKey('accounts.StudentProfile', on_delete=models.CASCADE, related_name='group_memberships')
    role = models.CharField(
        max_length=20,
        choices=[('MEMBER', 'Group Member'), ('LEADER', 'Team Leader / Contact')],
        default='MEMBER'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'asms_group_memberships'
        unique_together = ('study_group', 'student')


class Poll(models.Model):
    """
    Democratic class polling and student proposals with HMAC-SHA256 anonymous voter hash.
    """
    TYPE_CHOICES = [
        ('VOTE', 'Standard Choice Poll'),
        ('PROPOSAL', 'Class Proposal (Support / Oppose / Abstain)'),
    ]
    STATUS_CHOICES = [
        ('ACTIVE', 'Active / Open for Voting'),
        ('CLOSED', 'Closed / Concluded'),
    ]

    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, related_name='polls')
    classroom = models.ForeignKey('academics.Classroom', on_delete=models.CASCADE, related_name='polls')
    classroom_subject = models.ForeignKey(
        'academics.ClassroomSubject',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    
    is_anonymous = models.BooleanField(default=True)
    poll_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='VOTE')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    
    proposal_action = models.CharField(max_length=255, null=True, blank=True)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'asms_polls'

    def __str__(self):
        return f"[{self.status}] {self.title}"


class PollOption(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='options')
    text = models.CharField(max_length=255)
    vote_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'asms_poll_options'


class PollVote(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='votes')
    student = models.ForeignKey('accounts.StudentProfile', on_delete=models.SET_NULL, null=True, blank=True)
    voter_hash = models.CharField(max_length=128, db_index=True)
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, null=True, blank=True)
    vote_type = models.CharField(max_length=20, default='OPTION')
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'asms_poll_votes'
        unique_together = ('poll', 'voter_hash')


class StudentFeedback(models.Model):
    """
    Student grievance and feedback triage channel.
    """
    CATEGORY_CHOICES = [
        ('ACADEMIC', 'Academic / Teaching Pace'),
        ('FACILITIES', 'Laboratory & Equipment'),
        ('TIMETABLE', 'Timetable Clashes / Room Allocations'),
        ('ADMINISTRATIVE', 'Administrative / Registration'),
    ]
    STATUS_CHOICES = [
        ('SUBMITTED', 'Submitted'),
        ('UNDER_REVIEW', 'Under Review / Acknowledged'),
        ('RESOLVED', 'Resolved'),
        ('DISMISSED', 'Dismissed'),
    ]

    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, related_name='feedback_entries')
    classroom = models.ForeignKey('academics.Classroom', on_delete=models.CASCADE, related_name='feedback_entries')
    classroom_subject = models.ForeignKey(
        'academics.ClassroomSubject',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    student = models.ForeignKey('accounts.StudentProfile', on_delete=models.SET_NULL, null=True, blank=True)
    is_anonymous = models.BooleanField(default=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='ACADEMIC')
    title = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUBMITTED')
    teacher_response = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'asms_student_feedback'
        ordering = ['-created_at']


class AuditLog(models.Model):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, related_name='class_audit_logs', null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    user_name = models.CharField(max_length=255)
    user_role = models.CharField(max_length=50)
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=100)
    details = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'asms_audit_logs'
        ordering = ['-timestamp']
