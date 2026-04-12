"""arq worker settings.

The worker is populated with real jobs in ``app/worker/jobs``. This module
wires the Redis connection and cron schedule that the arq CLI expects.
"""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import settings
from app.worker.jobs.delete_expired_accounts import delete_expired_accounts


def _redis_settings() -> RedisSettings:
    """Build arq RedisSettings from the app Redis URL."""
    return RedisSettings.from_dsn(settings.REDIS_URL)


class WorkerSettings:
    """Entry point for ``arq app.worker.settings.WorkerSettings``."""

    redis_settings = _redis_settings()
    functions: list = [delete_expired_accounts]
    cron_jobs = [
        cron(
            delete_expired_accounts,
            hour={settings.DELETION_JOB_CRON_HOUR},
            minute={settings.DELETION_JOB_CRON_MINUTE},
            run_at_startup=False,
        ),
    ]
    max_jobs = 10
    job_timeout = 600
    keep_result = 3600
    health_check_interval = 60
