"""
Notifications helper (thin wrapper) for class_management scaffold.

This module provides helper functions that call into the existing
communications.services.publish function. It keeps calls idempotent and
centralizes variable names for templates.

Do NOT configure or change communications delivery here. This is a wrapper
that will be used by real implementations after scaffold review and approval.
"""

from django.db import transaction


def publish_material_uploaded(material_id, classroom_subject_id, uploaded_by_id, notify_email=True):
    """Publish a material-uploaded event via communications.services.publish.

    This is a non-blocking wrapper intended for use in service code.
    For V1, communications.publish will be called synchronously via
    transaction.on_commit. For high-volume scenarios, change to enqueue
    a task when Celery is configured.
    """
    # Lazy import to avoid startup dependency
    try:
        from communications import services as comm_services
    except Exception:
        # communications not available in some test contexts — fail silently in scaffold
        return

    # Build payload — actual template variables to be defined later
    payload = {
        "event": "material_uploaded",
        "material_id": material_id,
        "classroom_subject_id": classroom_subject_id,
        "uploaded_by_id": uploaded_by_id,
        "notify_email": notify_email,
    }

    # Use transaction.on_commit to ensure publish occurs after DB transaction
    transaction.on_commit(lambda: comm_services.publish(**payload))
