"""
These tests exercise the registry/service layer directly (no DB models
required beyond Django's ContentType/app registry) so they can run before
the full project's Student/Finance models are wired in. Once integrated,
extend with real querysets per the INTEGRATION NOTEs in
services/custom_report_service.py.
"""
from unittest.mock import MagicMock

import pytest

from reports.exceptions import RegistryError, ValidationError
from reports.registry import reportable_fields as registry
from reports.services import report_registry_service


class FakeUser:
    def __init__(self, role, is_superuser=False):
        self.role = role
        self.is_superuser = is_superuser


def test_admin_sees_all_whitelisted_sources():
    user = FakeUser("ADMIN")
    sources = report_registry_service.get_available_sources(user)
    keys = {s.source_key for s in sources}
    assert "students" in keys
    assert "finance_invoices" in keys


def test_teacher_does_not_see_finance_source():
    user = FakeUser("TEACHER")
    sources = report_registry_service.get_available_sources(user)
    keys = {s.source_key for s in sources}
    assert "finance_invoices" not in keys
    assert "students" in keys


def test_unapproved_field_is_rejected():
    user = FakeUser("ADMIN")
    field = report_registry_service.validate_field_access("students", "does_not_exist", user)
    assert field is None


def test_sensitive_field_never_in_registry():
    """National ID / DOB must never be reportable, for any role."""
    for role in ("ADMIN", "SUPERUSER", "TEACHER", "ACCOUNTANT"):
        user = FakeUser(role, is_superuser=(role == "SUPERUSER"))
        assert report_registry_service.validate_field_access("students", "national_id", user) is None
        assert report_registry_service.validate_field_access("students", "date_of_birth", user) is None


def test_finance_field_rejected_for_teacher():
    user = FakeUser("TEACHER")
    field = report_registry_service.validate_field_access("finance_invoices", "balance", user)
    assert field is None


def test_finance_field_allowed_for_accountant():
    user = FakeUser("ACCOUNTANT")
    field = report_registry_service.validate_field_access("finance_invoices", "balance", user)
    assert field is not None
    assert field.field_key == "balance"


def test_superuser_bypasses_role_but_field_must_still_exist():
    user = FakeUser("whatever_junk_role", is_superuser=True)
    field = report_registry_service.validate_field_access("finance_invoices", "balance", user)
    assert field is not None
    assert report_registry_service.validate_field_access("finance_invoices", "no_such_field", user) is None


class TestCustomReportServiceSecurity:
    """
    Exercises custom_report_service against a mocked ORM model to prove:
      - school scoping is always injected first
      - unapproved fields raise RegistryError, never silently ignored
      - malformed filter values are rejected by type coercion
    """

    def _patch_model(self, monkeypatch):
        fake_qs = MagicMock()
        fake_qs.filter.return_value = fake_qs
        fake_qs.values.return_value = fake_qs
        fake_qs.annotate.return_value = fake_qs
        fake_qs.order_by.return_value = fake_qs
        fake_qs.__getitem__.return_value = fake_qs

        fake_manager = MagicMock()
        fake_manager.filter.return_value = fake_qs

        fake_model = MagicMock()
        fake_model.objects = fake_manager

        monkeypatch.setattr(
            "reports.services.custom_report_service.apps.get_model",
            lambda path: fake_model,
        )
        return fake_qs, fake_manager

    def test_school_filter_applied_before_user_filters(self, monkeypatch):
        from reports.services import custom_report_service

        fake_qs, fake_manager = self._patch_model(monkeypatch)
        user = FakeUser("ADMIN")
        school = MagicMock(name="school")

        custom_report_service.build_queryset(
            source_key="students", school=school, user=user,
            field_specs=[{"field_key": "full_name", "is_aggregate": False}],
            filter_specs=[], sort_specs=[], group_specs=[],
        )

        # First call to objects.filter() must be the mandatory school scope.
        fake_manager.filter.assert_called_once_with(school=school)

    def test_unapproved_field_raises_registry_error(self, monkeypatch):
        from reports.services import custom_report_service

        self._patch_model(monkeypatch)
        user = FakeUser("ADMIN")
        school = MagicMock()

        with pytest.raises(RegistryError):
            custom_report_service.build_queryset(
                source_key="students", school=school, user=user,
                field_specs=[{"field_key": "national_id", "is_aggregate": False}],
                filter_specs=[], sort_specs=[], group_specs=[],
            )

    def test_cross_source_field_rejected(self, monkeypatch):
        """A field_key that's valid on finance_invoices must not be usable on students."""
        from reports.services import custom_report_service

        self._patch_model(monkeypatch)
        user = FakeUser("ADMIN")
        school = MagicMock()

        with pytest.raises(RegistryError):
            custom_report_service.build_queryset(
                source_key="students", school=school, user=user,
                field_specs=[{"field_key": "balance", "is_aggregate": False}],  # finance-only field
                filter_specs=[], sort_specs=[], group_specs=[],
            )

    def test_malformed_date_filter_rejected(self, monkeypatch):
        from reports.services import custom_report_service

        self._patch_model(monkeypatch)
        user = FakeUser("ADMIN")
        school = MagicMock()

        with pytest.raises(ValidationError):
            custom_report_service.build_queryset(
                source_key="students", school=school, user=user,
                field_specs=[{"field_key": "full_name", "is_aggregate": False}],
                filter_specs=[{"field_key": "enrollment_date", "operator": "GT", "value": "DROP TABLE students;"}],
                sort_specs=[], group_specs=[],
            )

    def test_aggregate_on_non_aggregatable_field_rejected(self, monkeypatch):
        from reports.services import custom_report_service

        self._patch_model(monkeypatch)
        user = FakeUser("ACCOUNTANT")
        school = MagicMock()

        with pytest.raises(RegistryError):
            custom_report_service.build_queryset(
                source_key="finance_invoices", school=school, user=user,
                field_specs=[{"field_key": "term", "is_aggregate": True, "aggregate_function": "SUM"}],
                filter_specs=[], sort_specs=[], group_specs=[],
            )

    def test_invalid_aggregate_function_rejected(self, monkeypatch):
        from reports.services import custom_report_service

        self._patch_model(monkeypatch)
        user = FakeUser("ACCOUNTANT")
        school = MagicMock()

        with pytest.raises(ValidationError):
            custom_report_service.build_queryset(
                source_key="finance_invoices", school=school, user=user,
                field_specs=[{"field_key": "balance", "is_aggregate": True, "aggregate_function": "HACK"}],
                filter_specs=[], sort_specs=[], group_specs=[],
            )
