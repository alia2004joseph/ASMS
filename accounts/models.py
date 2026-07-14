# accounts/models.py

import secrets

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom manager for users who authenticate using email."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")

        email = self.normalize_email(email)

        user = self.model(
            email=email,
            **extra_fields,
        )

        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)

        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_active", False)
        extra_fields.setdefault(
            "approval_status",
            User.ApprovalStatus.PENDING,
        )
        # Accounts stay inactive until an admin approves them. Without this,
        # a freshly registered PENDING user could still log in immediately,
        # which defeats the approval gate.
        

        return self._create_user(
            email=email,
            password=password,
            **extra_fields,
        )

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault(
            "approval_status",
            User.ApprovalStatus.APPROVED,
        )

        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")

        return self._create_user(
            email=email,
            password=password,
            **extra_fields,
        )


class User(AbstractUser):
    """
    Main ASMS authentication model.

    Email is used for login instead of username.
    Role-specific information belongs in separate profile models.
    """

    username = None

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"
        GUARDIAN = "guardian", "Guardian"
        ACCOUNTANT = "accountant", "Accountant"

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    email = models.EmailField(
        unique=True,
        db_index=True,
    )

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    profile_picture = models.ImageField(
        upload_to="profile_pictures/%Y/%m/",
        blank=True,
        null=True,
    )

    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        db_index=True,
    )

    approved_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="accounts_approved",
        null=True,
        blank=True,
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    rejection_reason = models.CharField(
        max_length=255,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name", "email"]

    def clean(self):
        super().clean()

        if self.email:
            self.email = self.email.lower().strip()

        if self.approval_status == self.ApprovalStatus.APPROVED:
            self.rejection_reason = ""

        if (
            self.approval_status == self.ApprovalStatus.REJECTED
            and not self.rejection_reason
        ):
            raise ValidationError(
                {
                    "rejection_reason": (
                        "A rejection reason is required when rejecting an account."
                    )
                }
            )

    def _validate_approver(self, approved_by):
        if not approved_by or not approved_by.is_authenticated:
            raise ValidationError(
                "An authenticated administrator is required."
            )

        if approved_by.is_superuser:
            return

        if (
            not approved_by.is_active
            or approved_by.approval_status
            != self.ApprovalStatus.APPROVED
            or approved_by.role != self.Role.ADMIN
            or approved_by.school_id is None
        ):
            raise ValidationError(
                "Only an approved school administrator can perform this action."
            )

        if approved_by.school_id != self.school_id:
            raise ValidationError(
                "Administrators may only manage accounts from their own school."
            )
    
    def approve(self, approved_by):
        self._validate_approver(approved_by)

        self.approval_status = self.ApprovalStatus.APPROVED
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        self.rejection_reason = ""
        self.is_active = True

        self.save(
            update_fields=[
                "approval_status",
                "approved_by",
                "approved_at",
                "rejection_reason",
                "is_active",
                "updated_at",
            ]
        )
    
    def reject(self, approved_by, reason):
        self._validate_approver(approved_by)

        if not reason or not reason.strip():
            raise ValidationError(
                "A rejection reason is required."
            )

        self.approval_status = self.ApprovalStatus.REJECTED
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        self.rejection_reason = reason.strip()
        self.is_active = False

        self.save(
            update_fields=[
                "approval_status",
                "approved_by",
                "approved_at",
                "rejection_reason",
                "is_active",
                "updated_at",
            ]
        )

    @property
    def is_approved(self):
        return self.approval_status == self.ApprovalStatus.APPROVED

    def __str__(self):
        name = self.get_full_name().strip()

        if not name:
            name = self.email

        return f"{name} ({self.get_role_display()})"


class StudentProfile(models.Model):
    """
    Academic and administrative information belonging only to students.

    Restricted fields such as classroom and student ID should only be
    changed by authorized administrators.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
        limit_choices_to={"role": User.Role.STUDENT},
    )

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="student_profiles",
    )

    classroom = models.ForeignKey(
        "academics.Classroom",
        on_delete=models.SET_NULL,
        related_name="students",
        null=True,
        blank=True,
    )

    student_id_number = models.CharField(
        max_length=30,
    )

    admission_date = models.DateField(
        null=True,
        blank=True,
    )

    is_active_student = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student_id_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "student_id_number"],
                name="unique_student_id_per_school",
            )
        ]

    def clean(self):
        errors = {}

        if self.user_id:
            if self.user.role != User.Role.STUDENT:
                errors["user"] = (
                    "Only users with the student role can have a student profile."
                )

            if self.user.school_id != self.school_id:
                errors["school"] = (
                    "The student's profile school must match the user's school."
                )

            if self.classroom_id:
                if self.classroom.school_id != self.school_id:
                    errors["classroom"] = (
                        "The classroom must belong to the student's school."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student_id_number} - {self.user}"


class AccessCode(models.Model):
    """
    School-specific signup code used to prevent unauthorized registration.

    An access code determines the school and role of the registering user.
    """

    code = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
    )

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="access_codes",
    )

    role = models.CharField(
        max_length=20,
        choices=User.Role.choices,
    )

    max_uses = models.PositiveIntegerField(default=1)
    times_used = models.PositiveIntegerField(default=0)

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="access_codes_created",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_uses__gte=1),
                name="access_code_max_uses_at_least_one",
            ),
            models.CheckConstraint(
                condition=models.Q(times_used__gte=0),
                name="access_code_times_used_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(times_used__lte=F("max_uses")),
                name="access_code_usage_not_above_limit",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_code()
        self.code = self.code.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_code():
        """Generate a secure, readable registration code."""

        return secrets.token_urlsafe(12)[:16].upper()

    def is_valid(self):
        if not self.is_active:
            return False

        if self.expires_at and self.expires_at <= timezone.now():
            return False

        return self.times_used < self.max_uses

    @classmethod
    def consume(cls, code):
        """
        Safely validate and consume an access code.

        select_for_update prevents two registrations from consuming the
        final remaining use at the same time.

        NOTE: This uses queryset-level .update() rather than assigning an
        F() expression to the instance and calling .save(). AccessCode.save()
        always calls self.full_clean(), and full_clean() tries to coerce
        every field through its Python type (e.g. int() on an IntegerField).
        An F() expression is not an int, so assigning
        `access_code.times_used = F("times_used") + 1` followed by
        `access_code.save()` raises a ValidationError on every call.
        Using .update() avoids full_clean() entirely for this counter bump,
        which is fine since no field-level validation is needed here.
        """

        normalized_code = code.strip().upper()

        with transaction.atomic():
            try:
                access_code = cls.objects.select_for_update().get(
                    code=normalized_code
                )
            except cls.DoesNotExist as exc:
                raise ValidationError(
                    "The access code is invalid."
                ) from exc

            if not access_code.is_valid():
                raise ValidationError(
                    "The access code is inactive, expired, or fully used."
                )

            cls.objects.filter(pk=access_code.pk).update(
                times_used=F("times_used") + 1,
                updated_at=timezone.now(),
            )
            access_code.refresh_from_db()

            if access_code.times_used >= access_code.max_uses:
                cls.objects.filter(pk=access_code.pk).update(
                    is_active=False,
                    updated_at=timezone.now(),
                )
                access_code.is_active = False

            return access_code

    def __str__(self):
        return (
            f"{self.code} - {self.school} - "
            f"{self.get_role_display()}"
        )


class GuardianStudentLink(models.Model):
    """
    Connects a guardian account to a student account.

    Guardians log in using their own accounts. They should never log in
    using the student's credentials.
    """

    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_links",
        limit_choices_to={"role": User.Role.GUARDIAN},
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guardian_links",
        limit_choices_to={"role": User.Role.STUDENT},
    )

    relationship = models.CharField(
        max_length=50,
        blank=True,
        help_text="For example: mother, father, uncle or legal guardian.",
    )

    is_primary_guardian = models.BooleanField(default=False)

    can_receive_notifications = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["student", "-is_primary_guardian"]

        constraints = [
            models.UniqueConstraint(
                fields=["guardian", "student"],
                name="unique_guardian_student_link",
            ),
            models.UniqueConstraint(
                fields=["student"],
                condition=models.Q(is_primary_guardian=True),
                name="one_primary_guardian_per_student",
            ),
        ]

    def clean(self):
        errors = {}

        if self.guardian_id:
            if self.guardian.role != User.Role.GUARDIAN:
                errors["guardian"] = (
                    "The selected user must have the guardian role."
                )

        if self.student_id:
            if self.student.role != User.Role.STUDENT:
                errors["student"] = (
                    "The selected user must have the student role."
                )

        if self.guardian_id and self.student_id:
            if self.guardian_id == self.student_id:
                errors["student"] = (
                    "A user cannot be linked to themselves."
                )

            if self.guardian.school_id != self.student.school_id:
                errors["student"] = (
                    "Guardian and student must belong to the same school."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.guardian} → {self.student}"