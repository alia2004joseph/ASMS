"""Comprehensive tests for IDCard model.

Save as: reports/tests/test_id_card.py
Run: pytest reports/tests/test_id_card.py -q
"""

from datetime import date
from uuid import UUID
from django.core.exceptions import ObjectDoesNotExist, ValidationError


import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from reports.constants import IDCardHolderType, IDCardStatus
from reports.models.base import AbstractGeneratedArtifact, SchoolScopedModel, VersionedModel

try:
    from reports.models.id_cards import IDCard
except ImportError:
    from reports.models import IDCard


def field(name):
    return IDCard._meta.get_field(name)


def constraint(name):
    return next(c for c in IDCard._meta.constraints if c.name == name)


def index(name):
    return next(i for i in IDCard._meta.indexes if i.name == name)


class DummyHolder:
    def __init__(self, school_id=1):
        self.school_id = school_id


def make_card(**kw):
    card = IDCard(
        school_id=1,
        holder_type=IDCardHolderType.STUDENT,
        holder_content_type=ContentType(),
        holder_object_id=1,
        identification_number="STU-001",
        holder_name_snapshot="Alice",
        role_label="Student",
        role_context={"classroom":"S1"},
        valid_from=date(2026,1,1),
        valid_until=date(2026,12,31),
        verification_code="VERIFY001",
        emergency_contact={"name":"Parent"},
        card_status=IDCardStatus.ACTIVE,
        revocation_reason="",
        version=1,
        root_id=UUID("11111111-1111-1111-1111-111111111111"),
        is_latest=True,
        is_revoked=False,
    )
    for k,v in kw.items():
        setattr(card,k,v)
    return card


class TestMeta:
    def test_inheritance(self):
        assert issubclass(IDCard, AbstractGeneratedArtifact)
        assert issubclass(IDCard, VersionedModel)
        assert issubclass(IDCard, SchoolScopedModel)

    def test_ordering(self):
        assert IDCard._meta.ordering==["-created_at","-pk"]

    @pytest.mark.parametrize("name",[
        "id_card_valid_until_after_from",
        "id_card_version_gte_1",
        "id_card_revocation_reason_req",
        "unique_id_card_chain_version",
        "unique_latest_id_card",
    ])
    def test_constraints_exist(self,name):
        assert constraint(name).name==name

    def test_indexes(self):
        assert len(IDCard._meta.indexes)==5
        assert list(index("id_card_root_version_idx").fields)==["root_id","version"]


class TestFields:
    def test_holder_type_choices(self):
        assert tuple(field("holder_type").choices)==tuple(IDCardHolderType.choices)

    def test_status_choices(self):
        assert tuple(field("card_status").choices)==tuple(IDCardStatus.choices)

    def test_verification_unique(self):
        f=field("verification_code")
        assert f.unique and f.db_index

    def test_identification_help(self):
        assert "official" in field("identification_number").help_text.lower()

    def test_role_context_default(self):
        assert field("role_context").default()=={}

    def test_emergency_optional(self):
        f=field("emergency_contact")
        assert f.null and f.blank


class TestValidation:
    def test_valid(self,monkeypatch):
        c=make_card()
        monkeypatch.setattr(IDCard,"holder",DummyHolder(1),raising=False)
        c.clean()

    def test_date_order(self):
        c=make_card(valid_until=date(2025,1,1))
        with pytest.raises(ValidationError):
            c.clean()

    @pytest.mark.parametrize("value",[""," ","   "])
    def test_identification_required(self,value):
        c=make_card(identification_number=value)
        with pytest.raises(ValidationError):
            c.clean()

    @pytest.mark.parametrize("value",[""," ","   "])
    def test_holder_name_required(self,value):
        c=make_card(holder_name_snapshot=value)
        with pytest.raises(ValidationError):
            c.clean()

    def test_role_context_must_be_dict(self):
        c=make_card(role_context=[])
        with pytest.raises(ValidationError):
            c.clean()

    def test_emergency_contact_must_be_dict(self):
        c=make_card(emergency_contact=[])
        with pytest.raises(ValidationError):
            c.clean()

    def test_revoked_requires_reason(self):
        c=make_card(card_status=IDCardStatus.REVOKED,revocation_reason=" ")
        with pytest.raises(ValidationError):
            c.clean()

    def test_reason_not_allowed_when_active(self):
        c=make_card(revocation_reason="because")
        with pytest.raises(ValidationError):
            c.clean()

    def test_missing_holder(self, monkeypatch):
        class FakeContentType:
            def get_object_for_this_type(self, **kwargs):
                raise ObjectDoesNotExist

        c = make_card()
        c.holder_content_type_id = 999
        c.holder_object_id = 1

        monkeypatch.setattr(
            type(ContentType.objects),
            "get_for_id",
            lambda self, content_type_id: FakeContentType(),
        )

        with pytest.raises(ValidationError) as exc_info:
            c.clean()

        assert exc_info.value.message_dict == {
            "holder_object_id": [
                "The referenced ID-card holder does not exist."
            ]
        }

    def test_school_mismatch(self, monkeypatch):
        class FakeHolder:
            pk = 1
            school_id = 2

        class FakeContentType:
            def get_object_for_this_type(self, **kwargs):
                return FakeHolder()

        c = make_card()
        c.school_id = 1
        c.holder_content_type_id = 999
        c.holder_object_id = 1

        monkeypatch.setattr(
            type(ContentType.objects),
            "get_for_id",
            lambda self, content_type_id: FakeContentType(),
        )

        with pytest.raises(ValidationError) as exc_info:
            c.clean()

        assert exc_info.value.message_dict == {
            "holder_object_id": [
                "The holder must belong to the same school as the ID card."
            ]
        }

class TestString:
    @pytest.mark.parametrize("holder_type,label",IDCardHolderType.choices)
    def test_string(self,holder_type,label):
        c=make_card(holder_type=holder_type,identification_number="EMP-1")
        assert str(c)==f"{label} ID EMP-1 — v1"


class TestInheritedDefaults:
    def test_defaults(self):
        c=IDCard()
        assert c.version==1
        assert c.is_latest is True
        assert c.file_hash==""
        assert c.failure_message==""
        assert c.created_at is None
        assert c.root_id is not None