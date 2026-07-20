"""
THE WHITELIST. This is the single, static, code-reviewed source of truth
for what the Custom Report Builder is allowed to query.

Design intent -- read this before touching this file:

    * Nothing is reportable unless it appears here. There is NO admin UI,
      API, or database table that can add a field to this list at runtime.
      Adding a new reportable field is a pull request, by design, so a
      human reviews every new exposure of student/finance data.

    * Each entry maps an opaque `field_key` (the only thing the client
      ever sends) to a concrete Django ORM path (`orm_path`). The service
      layer (`custom_report_service.py`) NEVER accepts an ORM path from
      the client -- it only ever resolves client-sent `field_key` strings
      through this dict.

    * `allowed_roles` is checked on every lookup. A field can be
      whitelisted globally but still hidden from a particular role (e.g.
      raw payment method details hidden from Teachers).

    * Sensitive fields (national ID numbers, raw guardian phone numbers,
      detailed payment instrument data, etc.) are simply never added here.
      That is the primary control -- omission, not a runtime check alone.

INTEGRATION NOTE: `orm_path` strings below (e.g. "full_name",
"student__school") assume field names on the real Student/Invoice/Payment
models. Adjust to match your actual schema -- the *shape* of the registry
(data sources -> fields -> role gates) does not change.
"""
from dataclasses import dataclass, field
from typing import Optional

from reports.constants import FieldDataType


@dataclass(frozen=True)
class ReportableField:
    field_key: str
    display_label: str
    orm_path: str
    data_type: str
    allowed_roles: tuple = ("ADMIN", "SUPERUSER")
    is_aggregatable: bool = False


@dataclass(frozen=True)
class DataSource:
    source_key: str
    display_label: str
    base_model: str  # dotted app_label.ModelName, resolved lazily via apps.get_model
    school_path: str  # ORM path from base_model to its school FK, for mandatory scoping
    allowed_roles: tuple = ("ADMIN", "SUPERUSER")
    fields: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry definition
# ---------------------------------------------------------------------------

_STUDENT_FIELDS = {
    "full_name": ReportableField("full_name", "Full Name", "full_name", FieldDataType.STRING,
                                  allowed_roles=("ADMIN", "SUPERUSER", "TEACHER")),
    "student_number": ReportableField("student_number", "Student Number", "student_number",
                                       FieldDataType.STRING, allowed_roles=("ADMIN", "SUPERUSER", "TEACHER")),
    "classroom": ReportableField("classroom", "Classroom", "current_class__name", FieldDataType.STRING,
                                  allowed_roles=("ADMIN", "SUPERUSER", "TEACHER")),
    "enrollment_date": ReportableField("enrollment_date", "Enrollment Date", "enrollment_date",
                                        FieldDataType.DATE, allowed_roles=("ADMIN", "SUPERUSER")),
    "status": ReportableField("status", "Enrollment Status", "status", FieldDataType.ENUM,
                               allowed_roles=("ADMIN", "SUPERUSER", "TEACHER")),
    # NOTE: deliberately no national_id / guardian_phone / date_of_birth here.
}

_FINANCE_FIELDS = {
    "student_number": ReportableField("student_number", "Student Number", "student__student_number",
                                       FieldDataType.STRING, allowed_roles=("ADMIN", "SUPERUSER", "ACCOUNTANT")),
    "invoice_total": ReportableField("invoice_total", "Invoice Total", "total_amount", FieldDataType.NUMBER,
                                      allowed_roles=("ADMIN", "SUPERUSER", "ACCOUNTANT"), is_aggregatable=True),
    "amount_paid": ReportableField("amount_paid", "Amount Paid", "amount_paid", FieldDataType.NUMBER,
                                    allowed_roles=("ADMIN", "SUPERUSER", "ACCOUNTANT"), is_aggregatable=True),
    "balance": ReportableField("balance", "Outstanding Balance", "balance", FieldDataType.NUMBER,
                                allowed_roles=("ADMIN", "SUPERUSER", "ACCOUNTANT"), is_aggregatable=True),
    "term": ReportableField("term", "Term", "term__name", FieldDataType.STRING,
                             allowed_roles=("ADMIN", "SUPERUSER", "ACCOUNTANT")),
    "issue_date": ReportableField("issue_date", "Issue Date", "issue_date", FieldDataType.DATE,
                                   allowed_roles=("ADMIN", "SUPERUSER", "ACCOUNTANT")),
    # NOTE: deliberately no raw payment instrument / card / mobile-money
    # account details here.
}

_ATTENDANCE_FIELDS = {
    "student_number": ReportableField("student_number", "Student Number", "student__student_number",
                                       FieldDataType.STRING, allowed_roles=("ADMIN", "SUPERUSER", "TEACHER")),
    "date": ReportableField("date", "Date", "date", FieldDataType.DATE,
                             allowed_roles=("ADMIN", "SUPERUSER", "TEACHER")),
    "status": ReportableField("status", "Attendance Status", "status", FieldDataType.ENUM,
                               allowed_roles=("ADMIN", "SUPERUSER", "TEACHER")),
}

DATA_SOURCES: dict = {
    "students": DataSource(
        source_key="students",
        display_label="Students",
        base_model="accounts.StudentProfile",
        school_path="school",
        allowed_roles=("ADMIN", "SUPERUSER", "TEACHER"),
        fields=_STUDENT_FIELDS,
    ),
    "finance_invoices": DataSource(
        source_key="finance_invoices",
        display_label="Student Invoices",
        base_model="finance.StudentInvoice",
        school_path="student__school",
        allowed_roles=("ADMIN", "SUPERUSER", "ACCOUNTANT"),
        fields=_FINANCE_FIELDS,
    ),
    "attendance_records": DataSource(
        source_key="attendance_records",
        display_label="Attendance Records",
        base_model="attendance.AttendanceRecord",
        school_path="student__school",
        allowed_roles=("ADMIN", "SUPERUSER", "TEACHER"),
        fields=_ATTENDANCE_FIELDS,
    ),
}


def get_sources_for_role(role: str) -> list:
    return [s for s in DATA_SOURCES.values() if role in s.allowed_roles]


def get_source(source_key: str) -> Optional[DataSource]:
    return DATA_SOURCES.get(source_key)


def get_fields_for_role(source_key: str, role: str) -> list:
    source = get_source(source_key)
    if source is None:
        return []
    return [f for f in source.fields.values() if role in f.allowed_roles]


def resolve_field(source_key: str, field_key: str, role: str) -> Optional[ReportableField]:
    """
    Returns the ReportableField only if it exists AND the role is allowed
    to use it. Returns None otherwise -- callers must treat None as "this
    field does not exist" (a 400/403), never fall back to a raw lookup.
    """
    source = get_source(source_key)
    if source is None:
        return None
    f = source.fields.get(field_key)
    if f is None or role not in f.allowed_roles:
        return None
    return f