"""
Domain exceptions for the Reports module.

Service layer code should raise only these exceptions.
The API layer (serializers/views) is responsible for translating them into
appropriate HTTP responses.
"""

from __future__ import annotations


class ReportsError(Exception):
    """
    Base exception for all Reports domain errors.
    """


class PermissionDeniedError(ReportsError):
    """
    Raised when the current user is not authorized to perform
    a Reports operation.

    This exception is independent of DRF permission classes and
    can be raised from any service.
    """


class ValidationError(ReportsError):
    """
    Raised when business-rule validation fails inside the service layer.

    This is distinct from DRF serializer validation.
    """


class NotEligibleError(ReportsError):
    """
    Raised when a report cannot be generated because the
    subject does not satisfy eligibility requirements.

    Examples
    --------
    - Outstanding school fees
    - Missing examination results
    - Graduation requirements not met
    - Missing mandatory approvals
    """


class RegistryError(ReportsError):
    """
    Raised when a custom report references an unknown
    registry source or field.
    """


class ResourceNotFoundError(ReportsError):
    """
    Raised when a requested Reports resource
    cannot be found.
    """


class ConflictError(ReportsError):
    """
    Raised when the requested operation conflicts with
    the current state of a resource.

    Examples
    --------
    - Regenerating a revoked certificate
    - Issuing a duplicate active ID card
    - Creating a transcript version conflict
    """


class ExportError(ReportsError):
    """
    Raised when report export generation fails.
    """


class VerificationError(ReportsError):
    """
    Raised when verification of a certificate,
    transcript, or ID card fails.
    """