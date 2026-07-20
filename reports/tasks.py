"""
Celery tasks for the Reports module.

Tasks are deliberately thin orchestration boundaries. They must not contain
ORM business workflows, report calculations, export construction, or status
transition logic. All domain behavior belongs to Reports services.

Every task accepts primitive identifiers so messages remain serializable and
safe to retry.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.db import DatabaseError, OperationalError

from reports.exceptions import ReportsError
from reports.services import bulk_export_service, custom_report_service

logger = logging.getLogger(__name__)

DEFAULT_RETRY_DELAY_SECONDS = 30
MAX_RETRIES = 3


@shared_task(
    bind=True,
    name="reports.execute_custom_report",
    max_retries=MAX_RETRIES,
    default_retry_delay=DEFAULT_RETRY_DELAY_SECONDS,
    acks_late=True,
    reject_on_worker_lost=True,
)
def execute_custom_report_task(
    self,
    definition_id: int,
    user_id: int,
    *,
    export_format: str = "EXCEL",
    execution_id: int | None = None,
) -> int:
    """
    Execute a saved custom-report definition asynchronously.

    The service owns:
    - definition and user resolution;
    - school and permission validation;
    - execution-record creation or reuse;
    - queryset construction;
    - export generation and persistence;
    - report and execution status transitions;
    - idempotency.

    Returns the generated-report primary key.
    """
    try:
        generated_report = custom_report_service.execute_custom_report(
            definition_id=definition_id,
            requested_by_id=user_id,
            export_format=export_format,
            execution_id=execution_id,
            task_id=self.request.id,
        )
    except ReportsError:
        logger.warning(
            "Custom report execution rejected by a domain rule.",
            extra={
                "definition_id": definition_id,
                "user_id": user_id,
                "execution_id": execution_id,
                "task_id": self.request.id,
            },
            exc_info=True,
        )
        raise
    except (OperationalError, DatabaseError) as exc:
        logger.warning(
            "Transient database failure while executing a custom report.",
            extra={
                "definition_id": definition_id,
                "user_id": user_id,
                "execution_id": execution_id,
                "task_id": self.request.id,
                "retry_count": self.request.retries,
            },
            exc_info=True,
        )
        raise self.retry(exc=exc)
    except Exception:
        logger.exception(
            "Unexpected custom report task failure.",
            extra={
                "definition_id": definition_id,
                "user_id": user_id,
                "execution_id": execution_id,
                "task_id": self.request.id,
            },
        )
        raise

    return generated_report.pk


@shared_task(
    bind=True,
    name="reports.build_bulk_archive",
    max_retries=MAX_RETRIES,
    default_retry_delay=DEFAULT_RETRY_DELAY_SECONDS,
    acks_late=True,
    reject_on_worker_lost=True,
)
def build_bulk_archive_task(
    self,
    job_id: int,
) -> int:
    """
    Finalize a bulk-report job and build its downloadable archive.

    The service owns job resolution, locking, state validation, archive
    construction, checksum generation, persistence, and idempotency.

    Returns the archive primary key.
    """
    try:
        archive = bulk_export_service.finalize_and_build_archive(
            job_id=job_id,
            task_id=self.request.id,
        )
    except ReportsError:
        logger.warning(
            "Bulk archive generation rejected by a domain rule.",
            extra={
                "job_id": job_id,
                "task_id": self.request.id,
            },
            exc_info=True,
        )
        raise
    except (OperationalError, DatabaseError) as exc:
        logger.warning(
            "Transient database failure while building a bulk archive.",
            extra={
                "job_id": job_id,
                "task_id": self.request.id,
                "retry_count": self.request.retries,
            },
            exc_info=True,
        )
        raise self.retry(exc=exc)
    except Exception:
        logger.exception(
            "Unexpected bulk archive task failure.",
            extra={
                "job_id": job_id,
                "task_id": self.request.id,
            },
        )
        raise

    return archive.pk


@shared_task(
    name="reports.cleanup_expired_archives",
    ignore_result=True,
)
def cleanup_expired_archives_task() -> None:
    """
    Delete expired bulk-export archives and update their persisted state.

    Register this task with Celery Beat at an appropriate interval.
    """
    deleted_count = bulk_export_service.cleanup_expired_archives()

    logger.info(
        "Expired Reports archives cleanup completed.",
        extra={"deleted_count": deleted_count},
    )


@shared_task(
    bind=True,
    name="reports.recover_stale_jobs",
    max_retries=MAX_RETRIES,
    default_retry_delay=DEFAULT_RETRY_DELAY_SECONDS,
    ignore_result=True,
)
def recover_stale_report_jobs_task(
    self,
    *,
    stale_after_minutes: int = 30,
) -> None:
    """
    Recover report jobs left in a processing state after worker interruption.

    The service decides which jobs are stale and whether they should be
    retried, failed, or returned to a queued state.
    """
    try:
        recovered_count = bulk_export_service.recover_stale_jobs(
            stale_after_minutes=stale_after_minutes,
        )
    except (OperationalError, DatabaseError) as exc:
        raise self.retry(exc=exc)

    logger.info(
        "Stale Reports jobs recovery completed.",
        extra={
            "recovered_count": recovered_count,
            "stale_after_minutes": stale_after_minutes,
        },
    )