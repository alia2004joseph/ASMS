"""
Tests for reports.serializers.bulk_export_serializers.

Run:
    pytest reports/tests/test_bulk_serializers.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework import serializers

from reports.constants import BulkJobType
from reports.exceptions import ValidationError as DomainValidationError
from reports.models.bulk_jobs import (
    BulkExportArchive,
    BulkReportItem,
    BulkReportJob,
)
from reports.serializers.bulk_export_serializers import (
    BulkExportArchiveSerializer,
    BulkJobCreateRequestSerializer,
    BulkReportItemSerializer,
    BulkReportJobSerializer,
)
from reports.serializers import bulk_export_serializers as serializer_module


def first_job_type_value():
    return BulkJobType.choices[0][0]


def make_request(*, user=None, school=None):
    if user is None:
        user = SimpleNamespace(
            school=school or SimpleNamespace(pk=1),
        )
    return SimpleNamespace(user=user)


def make_create_serializer(*, data=None, request=None):
    return BulkJobCreateRequestSerializer(
        data=data or {
            "job_type": first_job_type_value(),
            "parameters": {"scope": "SCHOOL"},
        },
        context={"request": request or make_request()},
    )


def make_job(**overrides):
    values = {
        "id": 1,
        "job_type": first_job_type_value(),
        "status": "PENDING",
        "total_items": 10,
        "completed_items": 4,
        "failed_items": 1,
        "started_at": None,
        "finished_at": None,
        "created_at": None,
        "items": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_item(**overrides):
    values = {
        "id": 1,
        "target_object_id": 25,
        "status": "PENDING",
        "generated_report_id": None,
        "error_message": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_archive(**overrides):
    values = {
        "id": 1,
        "job_id": 15,
        "expires_at": None,
        "downloaded_count": 0,
        "status": "READY",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestBulkJobCreateRequestSerializerFields:
    def test_exact_fields(self):
        assert tuple(BulkJobCreateRequestSerializer().fields) == (
            "job_type",
            "parameters",
        )

    def test_job_type_field(self):
        field = BulkJobCreateRequestSerializer().fields["job_type"]
        assert isinstance(field, serializers.ChoiceField)
        assert list(field.choices.items()) == list(BulkJobType.choices)

    def test_parameters_field(self):
        field = BulkJobCreateRequestSerializer().fields["parameters"]
        assert isinstance(field, serializers.JSONField)
        assert field.required is True


class TestBulkJobCreateRequestSerializerParameters:
    @pytest.mark.parametrize(
        "value",
        [[], (), "scope", 1, 1.5, True, False],
    )
    def test_parameters_must_be_object(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": value,
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "parameters must be a JSON object."
        ]

    def test_unknown_parameters_sorted(self):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {
                    "scope": "SCHOOL",
                    "zeta": 1,
                    "alpha": 2,
                },
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "Unknown parameter(s): alpha, zeta."
        ]

    @pytest.mark.parametrize(
        "parameters",
        [
            {},
            {"class_id": 1, "student_ids": [1]},
            {"class_id": 1, "scope": "SCHOOL"},
            {"student_ids": [1], "scope": "SCHOOL"},
            {
                "class_id": 1,
                "student_ids": [1],
                "scope": "SCHOOL",
            },
        ],
    )
    def test_exactly_one_selector_required(self, parameters):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": parameters,
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "Specify exactly one of class_id, student_ids or scope."
        ]


class TestClassIDValidation:
    @pytest.mark.parametrize(
        "value",
        ["1", 1.5, [], {}, None, True, False],
    )
    def test_class_id_must_be_integer(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"class_id": value},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "class_id must be an integer."
        ]

    @pytest.mark.parametrize("value", [-1, 0])
    def test_class_id_must_be_positive(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"class_id": value},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "class_id must be a positive integer."
        ]

    @pytest.mark.parametrize("value", [1, 999999])
    def test_valid_class_id(self, value, monkeypatch):
        validate_mock = Mock(return_value=None)
        monkeypatch.setattr(
            serializer_module.bulk_export_service,
            "validate_bulk_request",
            validate_mock,
        )
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"class_id": value},
            }
        )
        assert serializer.is_valid(), serializer.errors


class TestStudentIDsValidation:
    @pytest.mark.parametrize(
        "value",
        [[], (), "1,2", 1, {}, None],
    )
    def test_student_ids_must_be_nonempty_list(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"student_ids": value},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "student_ids must be a non-empty list."
        ]

    @pytest.mark.parametrize(
        "value",
        [
            [1, "2"],
            [1, 2.0],
            [1, None],
            [1, {}],
            [1, []],
            [True],
            [False],
        ],
    )
    def test_student_ids_must_contain_integers(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"student_ids": value},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "student_ids must contain integers."
        ]

    @pytest.mark.parametrize(
        "value",
        [[-1], [0], [1, 0], [1, -2]],
    )
    def test_student_ids_must_be_positive(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"student_ids": value},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "student_ids must contain positive integers."
        ]

    @pytest.mark.parametrize(
        "value",
        [[1, 1], [1, 2, 1], [5, 5, 5]],
    )
    def test_duplicate_student_ids_rejected(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"student_ids": value},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "Duplicate student_ids are not allowed."
        ]

    @pytest.mark.parametrize(
        "value",
        [[1], [1, 2, 3], [999999]],
    )
    def test_valid_student_ids(self, value, monkeypatch):
        validate_mock = Mock(return_value=None)
        monkeypatch.setattr(
            serializer_module.bulk_export_service,
            "validate_bulk_request",
            validate_mock,
        )
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"student_ids": value},
            }
        )
        assert serializer.is_valid(), serializer.errors


class TestScopeValidation:
    def test_school_scope_valid(self, monkeypatch):
        validate_mock = Mock(return_value=None)
        monkeypatch.setattr(
            serializer_module.bulk_export_service,
            "validate_bulk_request",
            validate_mock,
        )
        serializer = make_create_serializer()
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.parametrize(
        "value",
        ["school", "CLASS", "ALL", "", None, 1, True],
    )
    def test_other_scopes_invalid(self, value):
        serializer = make_create_serializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"scope": value},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["parameters"] == [
            "Only SCHOOL is currently supported."
        ]


class TestServiceValidation:
    def test_service_called_with_expected_arguments(
        self,
        monkeypatch,
    ):
        school = SimpleNamespace(pk=77)
        user = SimpleNamespace(school=school)
        validate_mock = Mock(return_value=None)

        monkeypatch.setattr(
            serializer_module.bulk_export_service,
            "validate_bulk_request",
            validate_mock,
        )

        serializer = make_create_serializer(
            request=make_request(user=user),
        )
        assert serializer.is_valid(), serializer.errors

        validate_mock.assert_called_once_with(
            school=school,
            user=user,
            job_type=first_job_type_value(),
            parameters={"scope": "SCHOOL"},
        )

    def test_domain_error_converted(self, monkeypatch):
        monkeypatch.setattr(
            serializer_module.bulk_export_service,
            "validate_bulk_request",
            Mock(
                side_effect=DomainValidationError(
                    "Bulk export is not permitted."
                )
            ),
        )
        serializer = make_create_serializer()
        assert not serializer.is_valid()
        assert serializer.errors["non_field_errors"] == [
            "Bulk export is not permitted."
        ]

    def test_unexpected_exception_propagates(self, monkeypatch):
        monkeypatch.setattr(
            serializer_module.bulk_export_service,
            "validate_bulk_request",
            Mock(side_effect=RuntimeError("unexpected")),
        )
        serializer = make_create_serializer()
        with pytest.raises(RuntimeError, match="unexpected"):
            serializer.is_valid()

    def test_missing_request_context_is_validation_error(self):
        serializer = BulkJobCreateRequestSerializer(
            data={
                "job_type": first_job_type_value(),
                "parameters": {"scope": "SCHOOL"},
            }
        )
        assert not serializer.is_valid()
        assert serializer.errors["non_field_errors"] == [
            "Request context is required."
        ]

    def test_user_without_school_is_invalid(self):
        serializer = make_create_serializer(
            request=make_request(
                user=SimpleNamespace(school=None)
            )
        )
        assert not serializer.is_valid()
        assert serializer.errors["non_field_errors"] == [
            "The authenticated user must belong to a school."
        ]


class TestBulkReportItemSerializer:
    def test_contract(self):
        assert BulkReportItemSerializer.Meta.model is BulkReportItem
        assert BulkReportItemSerializer.Meta.fields == (
            "id",
            "target_object_id",
            "status",
            "generated_report_id",
            "error_message",
        )
        assert (
            BulkReportItemSerializer.Meta.read_only_fields
            == BulkReportItemSerializer.Meta.fields
        )

    def test_generated_report_id_field(self):
        field = BulkReportItemSerializer().fields[
            "generated_report_id"
        ]
        assert isinstance(field, serializers.IntegerField)
        assert field.read_only is True
        assert field.allow_null is True

    def test_serialization(self):
        data = BulkReportItemSerializer(
            make_item(
                id=5,
                target_object_id=88,
                status="COMPLETED",
                generated_report_id=44,
            )
        ).data
        assert data == {
            "id": 5,
            "target_object_id": 88,
            "status": "COMPLETED",
            "generated_report_id": 44,
            "error_message": "",
        }

    def test_all_input_ignored(self):
        serializer = BulkReportItemSerializer(
            data={
                "id": 10,
                "target_object_id": 20,
                "status": "FAILED",
                "generated_report_id": 30,
                "error_message": "failure",
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {}


class TestBulkReportJobSerializer:
    def test_contract(self):
        assert BulkReportJobSerializer.Meta.model is BulkReportJob
        assert BulkReportJobSerializer.Meta.fields == (
            "id",
            "job_type",
            "status",
            "total_items",
            "completed_items",
            "failed_items",
            "progress",
            "started_at",
            "finished_at",
            "created_at",
            "items",
        )

    @pytest.mark.parametrize(
        ("completed", "total", "expected"),
        [
            (0, 0, 0),
            (0, 10, 0.0),
            (1, 4, 25.0),
            (1, 3, 33.33),
            (2, 3, 66.67),
            (10, 10, 100.0),
        ],
    )
    def test_progress(self, completed, total, expected):
        serializer = BulkReportJobSerializer()
        assert serializer.get_progress(
            make_job(
                completed_items=completed,
                total_items=total,
            )
        ) == expected

    def test_nested_items(self):
        data = BulkReportJobSerializer(
            make_job(
                total_items=2,
                completed_items=1,
                items=[
                    make_item(
                        id=1,
                        generated_report_id=501,
                    ),
                    make_item(
                        id=2,
                        generated_report_id=None,
                    ),
                ],
            )
        ).data
        assert data["progress"] == 50.0
        assert len(data["items"]) == 2
        assert data["items"][0]["generated_report_id"] == 501
        assert data["items"][1]["generated_report_id"] is None


class TestBulkExportArchiveSerializer:
    def test_contract(self):
        assert (
            BulkExportArchiveSerializer.Meta.model
            is BulkExportArchive
        )
        assert BulkExportArchiveSerializer.Meta.fields == (
            "id",
            "job_id",
            "expires_at",
            "downloaded_count",
            "status",
        )

    def test_job_id_field(self):
        field = BulkExportArchiveSerializer().fields["job_id"]
        assert isinstance(field, serializers.IntegerField)
        assert field.read_only is True

    def test_serialization(self):
        data = BulkExportArchiveSerializer(
            make_archive(
                id=9,
                job_id=77,
                downloaded_count=3,
                status="READY",
            )
        ).data
        assert data["id"] == 9
        assert data["job_id"] == 77
        assert data["downloaded_count"] == 3
        assert data["status"] == "READY"

    def test_all_input_ignored(self):
        serializer = BulkExportArchiveSerializer(
            data={
                "id": 9,
                "job_id": 77,
                "expires_at": None,
                "downloaded_count": 3,
                "status": "READY",
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {}