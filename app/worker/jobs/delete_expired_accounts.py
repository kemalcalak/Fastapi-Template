"""Hard-delete accounts whose grace period has elapsed.

Runs on the arq cron schedule defined in ``app.worker.settings``. Safe to
run across multiple worker replicas — ``get_users_due_for_deletion`` uses
``FOR UPDATE SKIP LOCKED`` so workers never collide on the same row.
"""

from __future__ import annotations

import logging
import time
from typing import TypedDict

from arq import Retry  # noqa: F401  # re-exported for downstream retry policies

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.repositories.user import (
    bulk_hard_delete_users,
    get_users_due_for_deletion,
)
from app.schemas.worker import DeletionJobResult
from app.utils import utc_now

logger = logging.getLogger(__name__)


class JobContext(TypedDict, total=False):
    """Subset of the arq context this job relies on. ``total=False`` since
    arq populates many runtime keys (job_id, redis, score, enqueue_time...)
    that we never read here."""

    job_id: str


async def delete_expired_accounts(ctx: JobContext) -> DeletionJobResult:
    """Remove users past their grace window in bounded batches.

    Each batch opens a short-lived transaction so row locks acquired by
    ``SELECT ... FOR UPDATE SKIP LOCKED`` are released on commit. The loop
    exits when an empty batch is observed. Individual user failures are
    logged and skipped — they'll be retried on the next run.
    """
    _ = ctx
    start = time.monotonic()
    processed = 0
    failed = 0
    batch_limit = settings.DELETION_JOB_BATCH_SIZE

    while True:
        async with AsyncSessionLocal() as session, session.begin():
            users = await get_users_due_for_deletion(
                session, now=utc_now(), limit=batch_limit
            )
            if not users:
                break

            ids = [u.id for u in users]
            try:
                deleted = await bulk_hard_delete_users(session, ids)
                processed += deleted
            except Exception:
                failed += len(ids)
                logger.exception(
                    "delete_expired_accounts: batch delete failed",
                    extra={"batch_size": len(ids)},
                )

        if len(users) < batch_limit:
            break

    duration_ms = int((time.monotonic() - start) * 1000)
    result = DeletionJobResult(
        processed=processed, failed=failed, duration_ms=duration_ms
    )
    logger.info("delete_expired_accounts: completed", extra=result.model_dump())
    return result
