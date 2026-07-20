"""
Central enums for the Reports & Analytics module.

Keeping these choices in one file prevents magic strings from being
scattered across models, services, serializers, permissions, and tasks.
"""

from django.db import models

class GradingDisplayFormat(models.TextChoices):
    MARKS = "MARKS", "Marks"
    PERCENTAGE = "PERCENTAGE", "Percentage"
    LETTER = "LETTER", "Letter Grade"
    MARKS_AND_LETTER = "MARKS_AND_LETTER", "Marks and Letter Grade"

class BulkArchiveStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    READY = "READY", "Ready"
    EXPIRED = "EXPIRED", "Expired"
    FAILED = "FAILED", "Failed"

class VerificationResult(models.TextChoices):
    VALID = "VALID", "Valid"
    NOT_FOUND = "NOT_FOUND", "Not Found"
    REVOKED = "REVOKED", "Revoked"
    SUPERSEDED = "SUPERSEDED", "Superseded"

class CertificateStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    READY = "READY", "Ready"
    REVOKED = "REVOKED", "Revoked"



class PerformanceSnapshotSource(models.TextChoices):
    OFFICAL_DOCUMENT = "OFFICIAL_DOCUMENT", "Official Document"
    REPORT_CARD = "REPORT_CARD", "Report Card"
    RESULT_SLIP = "RESULT_SLIP", "Result Slip"
    TRANSCRIPT = "TRANSCRIPT", "Transcript"
    ANALYTICS_JOB = "ANALYTICS_JOB", "Scheduled Analytics Job"
    MANUAL = "MANUAL", "Manual Administrative Snapshot"

class IDCardHolderType(models.TextChoices):
    STUDENT = "STUDENT", "Student"
    TEACHER = "TEACHER", "Teacher"
    STAFF = "STAFF", "Staff"
    GUARDIAN = "GUARDIAN", "Guardian"


class IDCardStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REVOKED = "REVOKED", "Revoked"
    EXPIRED = "EXPIRED", "Expired"
    REGENERATED = "REGENERATED", "Regenerated"

class SeatAssignmentStatus(models.TextChoices):
    ASSIGNED = "ASSIGNED", "Assigned"
    ABSENT = "ABSENT", "Absent"
    MISSING_CANDIDATE = "MISSING_CANDIDATE", "Missing Candidate"


class InvigilatorRole(models.TextChoices):
    CHIEF = "CHIEF", "Chief Invigilator"
    ASSISTANT = "ASSISTANT", "Assistant Invigilator"

class ResultSlipOutcome(models.TextChoices):
    PASS = "PASS", "Pass"
    FAIL = "FAIL", "Fail"
    INCOMPLETE = "INCOMPLETE", "Incomplete"
    WITHHELD = "WITHHELD", "Withheld"
    NOT_APPLICABLE = "N/A", "Not Applicable"

class DocumentType(models.TextChoices):
    REPORT_CARD = "REPORT_CARD", "Report Card"
    PERMIT = "PERMIT", "Examination Permit"
    TRANSCRIPT = "TRANSCRIPT", "Transcript"
    CERTIFICATE = "CERTIFICATE", "Certificate"
    FINANCE_STATEMENT = "FINANCE_STATEMENT", "Finance Statement"
    RESULT_SLIP = "RESULT_SLIP", "Result Slip"
    ID_CARD = "ID_CARD", "ID Card"
    FEE_CLEARANCE = "FEE_CLEARANCE", "Fee Clearance Certificate"
    SEATING_LIST = "SEATING_LIST", "Seating List"
    CUSTOM = "CUSTOM", "Custom Report"


class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ISSUED = "ISSUED", "Issued"
    REVOKED = "REVOKED", "Revoked"
    REGENERATED = "REGENERATED", "Regenerated"
    EXPIRED = "EXPIRED", "Expired"


class VerificationResult(models.TextChoices):
    VALID = "VALID", "Valid"
    REVOKED = "REVOKED", "Revoked"
    EXPIRED = "EXPIRED", "Expired"
    NOT_FOUND = "NOT_FOUND", "Not Found"


class ReportCategory(models.TextChoices):
    ACADEMIC = "ACADEMIC", "Academic"
    ATTENDANCE = "ATTENDANCE", "Attendance"
    FINANCE = "FINANCE", "Finance"
    ANALYTICS = "ANALYTICS", "Analytics"
    ADMINISTRATIVE = "ADMINISTRATIVE", "Administrative"
    CUSTOM = "CUSTOM", "Custom"


class ExportFormat(models.TextChoices):
    PDF = "PDF", "PDF"
    EXCEL = "EXCEL", "Excel"
    CSV = "CSV", "CSV"
    ZIP = "ZIP", "ZIP Archive"


class GeneratedReportStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    READY = "READY", "Ready"
    FAILED = "FAILED", "Failed"


class ReportScope(models.TextChoices):
    STUDENT = "STUDENT", "Student"
    CLASS = "CLASS", "Class"
    SUBJECT = "SUBJECT", "Subject"
    SCHOOL = "SCHOOL", "School"
    CUSTOM = "CUSTOM", "Custom"


class ClearanceStatus(models.TextChoices):
    CLEARED = "CLEARED", "Cleared"
    CLEARED_WITH_OVERRIDE = "CLEARED_WITH_OVERRIDE", "Cleared with Override"
    NOT_CLEARED = "NOT_CLEARED", "Not Cleared"


class BulkJobType(models.TextChoices):
    REPORT_CARDS = "REPORT_CARDS", "Report Cards"
    RESULT_SLIPS = "RESULT_SLIPS", "Result Slips"
    PERMITS = "PERMITS", "Examination Permits"
    ID_CARDS = "ID_CARDS", "ID Cards"
    FEE_CLEARANCE = "FEE_CLEARANCE", "Fee Clearance Certificates"
    CUSTOM = "CUSTOM", "Custom Report"


class BulkJobStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS", "Partial Success"
    COMPLETE = "COMPLETE", "Complete"
    FAILED = "FAILED", "Failed"


class BulkItemStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class FilterOperator(models.TextChoices):
    EQ = "EQ", "Equals"
    NEQ = "NEQ", "Does Not Equal"
    GT = "GT", "Greater Than"
    GTE = "GTE", "Greater Than or Equal"
    LT = "LT", "Less Than"
    LTE = "LTE", "Less Than or Equal"
    IN = "IN", "In"
    BETWEEN = "BETWEEN", "Between"
    CONTAINS = "CONTAINS", "Contains"
    IS_NULL = "IS_NULL", "Is Empty"
    IS_NOT_NULL = "IS_NOT_NULL", "Is Not Empty"


class AggregateFunction(models.TextChoices):
    SUM = "SUM", "Sum"
    AVG = "AVG", "Average"
    COUNT = "COUNT", "Count"
    MIN = "MIN", "Minimum"
    MAX = "MAX", "Maximum"


class SortDirection(models.TextChoices):
    ASC = "ASC", "Ascending"
    DESC = "DESC", "Descending"


class FieldDataType(models.TextChoices):
    STRING = "STRING", "String"
    NUMBER = "NUMBER", "Number"
    INTEGER = "INTEGER", "Integer"
    DECIMAL = "DECIMAL", "Decimal"
    PERCENTAGE = "PERCENTAGE", "Percentage"
    DATE = "DATE", "Date"
    DATETIME = "DATETIME", "Datetime"
    BOOLEAN = "BOOLEAN", "Boolean"
    ENUM = "ENUM", "Enum"


class SignaturePosition(models.TextChoices):
    TOP_LEFT = "TOP_LEFT", "Top Left"
    TOP_CENTER = "TOP_CENTER", "Top Center"
    TOP_RIGHT = "TOP_RIGHT", "Top Right"
    BOTTOM_LEFT = "BOTTOM_LEFT", "Bottom Left"
    BOTTOM_CENTER = "BOTTOM_CENTER", "Bottom Center"
    BOTTOM_RIGHT = "BOTTOM_RIGHT", "Bottom Right"
    CUSTOM = "CUSTOM", "Custom Position"


class TemplateEngine(models.TextChoices):
    HTML = "HTML", "HTML"
    DOCX = "DOCX", "DOCX"


class PageOrientation(models.TextChoices):
    PORTRAIT = "PORTRAIT", "Portrait"
    LANDSCAPE = "LANDSCAPE", "Landscape"


class PageSize(models.TextChoices):
    A4 = "A4", "A4"
    LETTER = "LETTER", "Letter"