"""Sweep stale user sessions on the arq cron schedule.

Expired sessions carry no value and are deleted immediately; revoked ones are
kept for ``SESSION_REVOKED_RETENTION_DAYS`` (audit trail), then dropped. The
whole sweep is one set-based DELETE, so no batching loop is needed — Postgres
handles millions of rows in a single statement comfortably.
"""

from __future__ import annotations

import logging
import time
from typing import TypedDict

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.repositories.user_session import purge_stale_sessions as purge_repo
from app.schemas.worker import SessionPurgeJobResult

logger = logging.getLogger(__name__)


class JobContext(TypedDict, total=False):
    """Subset of the arq context this job relies on (none of it, currently)."""

    job_id: str


async def purge_stale_sessions(ctx: JobContext) -> SessionPurgeJobResult:
    """Delete expired sessions and long-revoked ones in one sweep."""
    _ = ctx
    start = time.monotonic()

    async with AsyncSessionLocal() as session:
        purged = await purge_repo(
            session,
            revoked_retention_days=settings.SESSION_REVOKED_RETENTION_DAYS,
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    result = SessionPurgeJobResult(purged=purged, duration_ms=duration_ms)
    logger.info("purge_stale_sessions: completed", extra=result.model_dump())
    return result
