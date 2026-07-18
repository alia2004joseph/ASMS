from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import GuardianStudentLink, User
from finance.permissions import (
    IsFinanceManager,
    IsOwnStudentOrLinkedGuardianReadOnly,
)


class FinancePermissionTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def build_request(self, user, method="get"):
        request_method = getattr(self.factory, method.lower())
        request = request_method("/api/finance/test/")
        force_authenticate(request, user=user)

        # Permission classes normally receive DRF Request objects.
        request.user = user
        return request

    def make_user(
        self,
        *,
        user_id=1,
        role=User.Role.ADMIN,
        school_id=1,
        approved=True,
        active=True,
        superuser=False,
    ):
        user = Mock(spec=User)
        user.id = user_id
        user.pk = user_id
        user.role = role
        user.school_id = school_id
        user.school = Mock(id=school_id)
        user.is_authenticated = True
        user.is_active = active
        user.is_superuser = superuser
        user.approval_status = (
            User.ApprovalStatus.APPROVED
            if approved
            else User.ApprovalStatus.PENDING
        )
        return user

    def test_approved_admin_can_manage_finance(self):
        user = self.make_user(role=User.Role.ADMIN)
        request = self.build_request(user)

        permission = IsFinanceManager()

        self.assertTrue(permission.has_permission(request, None))

    def test_approved_accountant_can_manage_finance(self):
        user = self.make_user(role=User.Role.ACCOUNTANT)
        request = self.build_request(user)

        permission = IsFinanceManager()

        self.assertTrue(permission.has_permission(request, None))

    def test_pending_admin_cannot_manage_finance(self):
        user = self.make_user(
            role=User.Role.ADMIN,
            approved=False,
        )
        request = self.build_request(user)

        permission = IsFinanceManager()

        self.assertFalse(permission.has_permission(request, None))

    def test_student_cannot_manage_finance(self):
        user = self.make_user(role=User.Role.STUDENT)
        request = self.build_request(user)

        permission = IsFinanceManager()

        self.assertFalse(permission.has_permission(request, None))

    def test_finance_manager_cannot_access_another_school_object(self):
        user = self.make_user(
            role=User.Role.ACCOUNTANT,
            school_id=1,
        )
        request = self.build_request(user)

        other_school_object = SimpleNamespace(school_id=2)

        permission = IsFinanceManager()

        self.assertFalse(
            permission.has_object_permission(
                request,
                None,
                other_school_object,
            )
        )

    def test_finance_manager_can_access_own_school_object(self):
        user = self.make_user(
            role=User.Role.ACCOUNTANT,
            school_id=1,
        )
        request = self.build_request(user)

        own_school_object = SimpleNamespace(school_id=1)

        permission = IsFinanceManager()

        self.assertTrue(
            permission.has_object_permission(
                request,
                None,
                own_school_object,
            )
        )

    def test_student_can_read_own_finance_record(self):
        user = self.make_user(
            user_id=10,
            role=User.Role.STUDENT,
        )
        request = self.build_request(user, method="get")

        student_profile = SimpleNamespace(user_id=10)
        finance_object = SimpleNamespace(student=student_profile)

        permission = IsOwnStudentOrLinkedGuardianReadOnly()

        self.assertTrue(permission.has_permission(request, None))
        self.assertTrue(
            permission.has_object_permission(
                request,
                None,
                finance_object,
            )
        )

    def test_student_cannot_read_another_students_record(self):
        user = self.make_user(
            user_id=10,
            role=User.Role.STUDENT,
        )
        request = self.build_request(user, method="get")

        another_student = SimpleNamespace(user_id=20)
        finance_object = SimpleNamespace(student=another_student)

        permission = IsOwnStudentOrLinkedGuardianReadOnly()

        self.assertFalse(
            permission.has_object_permission(
                request,
                None,
                finance_object,
            )
        )

    def test_student_cannot_modify_finance_record(self):
        user = self.make_user(
            user_id=10,
            role=User.Role.STUDENT,
        )
        request = self.build_request(user, method="post")

        permission = IsOwnStudentOrLinkedGuardianReadOnly()

        self.assertFalse(permission.has_permission(request, None))

    @patch.object(GuardianStudentLink.objects, "filter")
    def test_guardian_can_read_linked_students_record(self, mock_filter):
        guardian = self.make_user(
            user_id=50,
            role=User.Role.GUARDIAN,
        )
        request = self.build_request(guardian, method="get")

        mock_filter.return_value.values_list.return_value = [20]

        student_profile = SimpleNamespace(user_id=20)
        finance_object = SimpleNamespace(student=student_profile)

        permission = IsOwnStudentOrLinkedGuardianReadOnly()

        self.assertTrue(
            permission.has_object_permission(
                request,
                None,
                finance_object,
            )
        )

    @patch.object(GuardianStudentLink.objects, "filter")
    def test_guardian_cannot_read_unlinked_students_record(self, mock_filter):
        guardian = self.make_user(
            user_id=50,
            role=User.Role.GUARDIAN,
        )
        request = self.build_request(guardian, method="get")

        mock_filter.return_value.values_list.return_value = [20]

        unlinked_student = SimpleNamespace(user_id=30)
        finance_object = SimpleNamespace(student=unlinked_student)

        permission = IsOwnStudentOrLinkedGuardianReadOnly()

        self.assertFalse(
            permission.has_object_permission(
                request,
                None,
                finance_object,
            )
        )

    @patch.object(GuardianStudentLink.objects, "filter")
    def test_guardian_links_are_cached_per_request(self, mock_filter):
        guardian = self.make_user(
            user_id=50,
            role=User.Role.GUARDIAN,
        )
        request = self.build_request(guardian, method="get")

        mock_filter.return_value.values_list.return_value = [20, 21]

        first_object = SimpleNamespace(
            student=SimpleNamespace(user_id=20)
        )
        second_object = SimpleNamespace(
            student=SimpleNamespace(user_id=21)
        )

        permission = IsOwnStudentOrLinkedGuardianReadOnly()

        self.assertTrue(
            permission.has_object_permission(
                request,
                None,
                first_object,
            )
        )
        self.assertTrue(
            permission.has_object_permission(
                request,
                None,
                second_object,
            )
        )

        # The database lookup should happen only once.
        self.assertEqual(mock_filter.call_count, 1)

    @patch.object(GuardianStudentLink.objects, "filter")
    def test_permission_supports_receipt_through_payment(self, mock_filter):
        guardian = self.make_user(
            user_id=50,
            role=User.Role.GUARDIAN,
        )
        request = self.build_request(guardian, method="get")

        mock_filter.return_value.values_list.return_value = [20]

        student_profile = SimpleNamespace(user_id=20)
        payment = SimpleNamespace(student=student_profile)
        receipt = SimpleNamespace(payment=payment)

        permission = IsOwnStudentOrLinkedGuardianReadOnly()

        self.assertTrue(
            permission.has_object_permission(
                request,
                None,
                receipt,
            )
        )