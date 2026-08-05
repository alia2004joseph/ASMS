# communications/tests/test_services.py

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from academics.models import Classroom
from accounts.models import GuardianStudentLink, StudentProfile, User
from communications import services
from communications.models import Communication, CommunicationRecipient
from schools.models import School


def make_user(school, role, email, **extra):
    return User.objects.create_user(
        email=email,
        password="pass12345",
        role=role,
        school=school,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
        **extra,
    )


class AudienceResolutionTests(TestCase):
    def setUp(self):
        self.school_a = School.objects.create(name="School A", code="SA01")
        self.school_b = School.objects.create(name="School B", code="SB01")

        self.admin = make_user(self.school_a, User.Role.ADMIN, "admin@a.test")
        self.teacher = make_user(self.school_a, User.Role.TEACHER, "teacher@a.test")

        self.classroom = Classroom.objects.create(
            school=self.school_a, name="S1 East", code="S1E"
        )
        self.other_classroom = Classroom.objects.create(
            school=self.school_a, name="S1 West", code="S1W"
        )

        self.student_in = make_user(self.school_a, User.Role.STUDENT, "s1@a.test")
        StudentProfile.objects.create(
            user=self.student_in,
            school=self.school_a,
            classroom=self.classroom,
            student_id_number="A001",
        )

        self.student_out = make_user(self.school_a, User.Role.STUDENT, "s2@a.test")
        StudentProfile.objects.create(
            user=self.student_out,
            school=self.school_a,
            classroom=self.other_classroom,
            student_id_number="A002",
        )

        self.guardian = make_user(self.school_a, User.Role.GUARDIAN, "g1@a.test")
        GuardianStudentLink.objects.create(
            guardian=self.guardian, student=self.student_in, is_primary_guardian=True
        )

        self.stray_student_b = make_user(self.school_b, User.Role.STUDENT, "s@b.test")

    def test_all_students_scoped_to_school(self):
        comm = Communication.objects.create(
            school=self.school_a,
            title="T",
            body="B",
            created_by=self.admin,
            audience_type=Communication.AudienceType.ALL_STUDENTS,
        )
        recipients = services.resolve_recipients(comm)
        ids = set(recipients.keys())
        self.assertIn(self.student_in.id, ids)
        self.assertIn(self.student_out.id, ids)
        self.assertNotIn(self.stray_student_b.id, ids)

    def test_classroom_targeting_with_guardians(self):
        comm = Communication.objects.create(
            school=self.school_a,
            title="T",
            body="B",
            created_by=self.admin,
            audience_type=Communication.AudienceType.CLASSROOMS,
            include_guardians_of_targets=True,
        )
        comm.target_classrooms.set([self.classroom])

        recipients = services.resolve_recipients(comm)
        ids = set(recipients.keys())

        self.assertIn(self.student_in.id, ids)
        self.assertIn(self.guardian.id, ids)
        self.assertNotIn(self.student_out.id, ids)

    def test_deduplication(self):
        comm = Communication.objects.create(
            school=self.school_a,
            title="T",
            body="B",
            created_by=self.admin,
            audience_type=Communication.AudienceType.USERS,
        )
        comm.target_users.set([self.student_in, self.student_in])
        recipients = services.resolve_recipients(comm)
        self.assertEqual(len(recipients), 1)

    def test_cross_school_target_rejected(self):
        comm = Communication.objects.create(
            school=self.school_a,
            title="T",
            body="B",
            created_by=self.admin,
            audience_type=Communication.AudienceType.USERS,
        )
        with self.assertRaises(ValidationError):
            services.validate_targeting(comm, target_users=[self.stray_student_b])


class WorkflowTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="School C", code="SC01")
        self.admin = make_user(self.school, User.Role.ADMIN, "admin@c.test")
        self.teacher = make_user(self.school, User.Role.TEACHER, "teacher@c.test")
        self.student = make_user(self.school, User.Role.STUDENT, "s@c.test")

    def test_admin_publish_does_not_require_approval(self):
        comm = services.create_draft(
            self.admin,
            title="Notice",
            body="Body",
            audience_type=Communication.AudienceType.ALL_STUDENTS,
        )
        services.submit_for_approval(self.admin, comm)
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.DRAFT)

        with self.captureOnCommitCallbacks(execute=True):
            published = services.publish(self.admin, comm)
        published.refresh_from_db()
        self.assertEqual(published.status, Communication.Status.COMPLETED)
        self.assertEqual(
            CommunicationRecipient.objects.filter(communication=comm).count(),
            1,
        )

    def test_teacher_broadcast_requires_approval(self):
        comm = services.create_draft(
            self.teacher,
            title="Homework",
            body="Body",
            audience_type=Communication.AudienceType.USERS,
        )
        comm.target_users.set([self.student])
        services.submit_for_approval(self.teacher, comm)
        comm.refresh_from_db()
        self.assertEqual(comm.status, Communication.Status.PENDING_APPROVAL)

        with self.assertRaises(ValidationError):
            services.publish(self.teacher, comm)

        services.approve(self.admin, comm)
        comm.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            published = services.publish(self.teacher, comm)
        published.refresh_from_db()
        self.assertEqual(published.status, Communication.Status.COMPLETED)

    def test_teacher_cannot_target_whole_school(self):
        comm = services.create_draft(
            self.teacher,
            title="Broadcast",
            body="Body",
            audience_type=Communication.AudienceType.SCHOOL,
        )
        with self.assertRaises(PermissionDenied):
            services.submit_for_approval(self.teacher, comm)

    def test_student_cannot_create_communication(self):
        with self.assertRaises(PermissionDenied):
            services.create_draft(
                self.student,
                title="X",
                body="Y",
                audience_type=Communication.AudienceType.SCHOOL,
            )

    def test_reject_requires_reason(self):
        comm = services.create_draft(
            self.teacher,
            title="Notice",
            body="Body",
            audience_type=Communication.AudienceType.USERS,
        )
        comm.target_users.set([self.student])
        services.submit_for_approval(self.teacher, comm)
        comm.refresh_from_db()
        with self.assertRaises(ValidationError):
            services.reject(self.admin, comm, "")

    def test_cancel_blocks_terminal_states(self):
        comm = services.create_draft(
            self.admin,
            title="Notice",
            body="Body",
            audience_type=Communication.AudienceType.ALL_STUDENTS,
        )
        services.submit_for_approval(self.admin, comm)
        comm.refresh_from_db()
        services.publish(self.admin, comm)
        comm.refresh_from_db()
        services.cancel(self.admin, comm)
        comm.refresh_from_db()
        with self.assertRaises(ValidationError):
            services.cancel(self.admin, comm)


class DeliveryTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="School D", code="SD01")
        self.admin = make_user(self.school, User.Role.ADMIN, "admin@d.test")
        self.student = make_user(self.school, User.Role.STUDENT, "s@d.test")

    def test_email_delivery_idempotent_on_replay(self):
        comm = services.create_draft(
            self.admin,
            title="Notice",
            body="Body",
            audience_type=Communication.AudienceType.ALL_STUDENTS,
            channels=[
                CommunicationRecipient.Channel.IN_APP,
                CommunicationRecipient.Channel.EMAIL,
            ],
        )
        services.submit_for_approval(self.admin, comm)
        comm.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            services.publish(self.admin, comm)
        comm.refresh_from_db()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            CommunicationRecipient.objects.filter(communication=comm).count(), 2
        )

        # Re-running freeze_recipient_snapshot must not duplicate rows.
        created, total = services.freeze_recipient_snapshot(
            comm, [CommunicationRecipient.Channel.IN_APP, CommunicationRecipient.Channel.EMAIL]
        )
        self.assertEqual(created, 0)
        self.assertEqual(
            CommunicationRecipient.objects.filter(communication=comm).count(), 2
        )

    def test_acknowledgement_flow(self):
        comm = services.create_draft(
            self.admin,
            title="Notice",
            body="Body",
            audience_type=Communication.AudienceType.ALL_STUDENTS,
            requires_acknowledgement=True,
        )
        services.submit_for_approval(self.admin, comm)
        comm.refresh_from_db()
        services.publish(self.admin, comm)
        comm.refresh_from_db()

        pending = list(services.list_pending_acknowledgements(comm))
        self.assertEqual(len(pending), 1)

        services.acknowledge(self.student, comm)
        pending_after = list(services.list_pending_acknowledgements(comm))
        self.assertEqual(len(pending_after), 0)
