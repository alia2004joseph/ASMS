# communications/tests/test_models.py

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from communications.models import Communication, CommunicationRecipient
from schools.models import School


class CommunicationModelTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Kampala High", code="KH01")
        self.admin = User.objects.create_user(
            email="admin@kh.test",
            password="pass12345",
            role=User.Role.ADMIN,
            school=self.school,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_defaults(self):
        comm = Communication.objects.create(
            school=self.school,
            title="Welcome",
            body="Hello everyone",
            created_by=self.admin,
            audience_type=Communication.AudienceType.SCHOOL,
        )
        self.assertEqual(comm.status, Communication.Status.DRAFT)
        self.assertEqual(comm.priority, Communication.Priority.NORMAL)
        self.assertEqual(comm.communication_type, Communication.CommunicationType.GENERAL)

    def test_emergency_requires_urgent_priority(self):
        comm = Communication(
            school=self.school,
            title="Fire drill",
            body="Evacuate now",
            created_by=self.admin,
            audience_type=Communication.AudienceType.SCHOOL,
            communication_type=Communication.CommunicationType.EMERGENCY,
            priority=Communication.Priority.NORMAL,
        )
        with self.assertRaises(ValidationError):
            comm.save()

    def test_rejected_requires_reason(self):
        comm = Communication(
            school=self.school,
            title="Notice",
            body="Body",
            created_by=self.admin,
            audience_type=Communication.AudienceType.SCHOOL,
            status=Communication.Status.REJECTED,
        )
        with self.assertRaises(ValidationError):
            comm.save()

    def test_string_representation(self):
        comm = Communication.objects.create(
            school=self.school,
            title="Notice",
            body="Body",
            created_by=self.admin,
            audience_type=Communication.AudienceType.SCHOOL,
        )
        self.assertIn("Notice", str(comm))
        self.assertIn(self.school.name, str(comm))


class CommunicationRecipientModelTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Kampala High", code="KH02")
        self.admin = User.objects.create_user(
            email="admin2@kh.test",
            password="pass12345",
            role=User.Role.ADMIN,
            school=self.school,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.student = User.objects.create_user(
            email="student@kh.test",
            password="pass12345",
            role=User.Role.STUDENT,
            school=self.school,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.comm = Communication.objects.create(
            school=self.school,
            title="Notice",
            body="Body",
            created_by=self.admin,
            audience_type=Communication.AudienceType.ALL_STUDENTS,
        )

    def test_unique_delivery_per_channel(self):
        CommunicationRecipient.objects.create(
            communication=self.comm,
            recipient=self.student,
            channel=CommunicationRecipient.Channel.IN_APP,
        )
        with self.assertRaises(Exception):
            CommunicationRecipient.objects.create(
                communication=self.comm,
                recipient=self.student,
                channel=CommunicationRecipient.Channel.IN_APP,
            )

    def test_mark_read_and_acknowledged(self):
        record = CommunicationRecipient.objects.create(
            communication=self.comm,
            recipient=self.student,
            channel=CommunicationRecipient.Channel.IN_APP,
            status=CommunicationRecipient.DeliveryStatus.DELIVERED,
        )
        record.mark_read()
        self.assertIsNotNone(record.read_at)
        self.assertEqual(record.status, CommunicationRecipient.DeliveryStatus.READ)

        record.mark_acknowledged()
        self.assertIsNotNone(record.acknowledged_at)
        self.assertEqual(record.status, CommunicationRecipient.DeliveryStatus.ACKNOWLEDGED)
