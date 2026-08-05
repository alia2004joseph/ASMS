# communications/tests/test_api.py

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from communications.models import Communication, CommunicationRecipient
from schools.models import School


def make_user(school, role, email):
    return User.objects.create_user(
        email=email,
        password="pass12345",
        role=role,
        school=school,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    )


class CommunicationAPITests(APITestCase):
    def setUp(self):
        self.school_a = School.objects.create(name="School A", code="SAX1")
        self.school_b = School.objects.create(name="School B", code="SBX1")

        self.admin_a = make_user(self.school_a, User.Role.ADMIN, "admin@sa.test")
        self.student_a = make_user(self.school_a, User.Role.STUDENT, "s@sa.test")
        self.admin_b = make_user(self.school_b, User.Role.ADMIN, "admin@sb.test")

    def test_student_cannot_create_communication(self):
        self.client.force_authenticate(self.student_a)
        resp = self.client.post(
            "/api/communications/communications/",
            {
                "title": "X",
                "body": "Y",
                "audience_type": Communication.AudienceType.SCHOOL,
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_and_publish(self):
        self.client.force_authenticate(self.admin_a)
        resp = self.client.post(
            "/api/communications/communications/",
            {
                "title": "Assembly",
                "body": "All students report to the hall.",
                "audience_type": Communication.AudienceType.ALL_STUDENTS,
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        comm_id = resp.data["id"]

        resp = self.client.post(
            f"/api/communications/communications/{comm_id}/submit/"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                f"/api/communications/communications/{comm_id}/publish/"
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["status"], Communication.Status.PUBLISHED)

        comm = Communication.objects.get(id=comm_id)
        self.assertEqual(comm.status, Communication.Status.COMPLETED)

    def test_admin_cannot_see_other_school_communications(self):
        comm = Communication.objects.create(
            school=self.school_b,
            title="Private",
            body="Body",
            created_by=self.admin_b,
            audience_type=Communication.AudienceType.SCHOOL,
        )
        self.client.force_authenticate(self.admin_a)
        resp = self.client.get(f"/api/communications/communications/{comm.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_inbox_and_unread_count(self):
        comm = Communication.objects.create(
            school=self.school_a,
            title="Notice",
            body="Body",
            created_by=self.admin_a,
            audience_type=Communication.AudienceType.ALL_STUDENTS,
            status=Communication.Status.PUBLISHED,
        )
        record = CommunicationRecipient.objects.create(
            communication=comm,
            recipient=self.student_a,
            channel=CommunicationRecipient.Channel.IN_APP,
            status=CommunicationRecipient.DeliveryStatus.DELIVERED,
        )

        self.client.force_authenticate(self.student_a)

        resp = self.client.get("/api/communications/unread-count/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["unread_count"], 1)

        resp = self.client.get("/api/communications/inbox/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)

        resp = self.client.post(f"/api/communications/inbox/{record.id}/read/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp = self.client.get("/api/communications/unread-count/")
        self.assertEqual(resp.data["unread_count"], 0)

    def test_student_cannot_read_other_students_inbox_item(self):
        other_student = make_user(self.school_a, User.Role.STUDENT, "s2@sa.test")
        comm = Communication.objects.create(
            school=self.school_a,
            title="Notice",
            body="Body",
            created_by=self.admin_a,
            audience_type=Communication.AudienceType.ALL_STUDENTS,
            status=Communication.Status.PUBLISHED,
        )
        record = CommunicationRecipient.objects.create(
            communication=comm,
            recipient=other_student,
            channel=CommunicationRecipient.Channel.IN_APP,
            status=CommunicationRecipient.DeliveryStatus.DELIVERED,
        )
        self.client.force_authenticate(self.student_a)
        resp = self.client.post(f"/api/communications/inbox/{record.id}/read/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_notification_preferences_get_and_patch(self):
        self.client.force_authenticate(self.student_a)
        resp = self.client.get("/api/communications/preferences/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["in_app_enabled"])

        resp = self.client.patch(
            "/api/communications/preferences/me/", {"email_enabled": False}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["email_enabled"])
