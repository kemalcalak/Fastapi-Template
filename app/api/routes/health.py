import asyncio
import logging
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from fastapi import APIRouter, Response, status
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep
from app.core.redis import get_redis
from app.schemas.health import (
    CheckResult,
    LivenessResponse,
    ReadinessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_CHECK_TIMEOUT_SECONDS = 2.0

try:
    _APP_VERSION = _pkg_version("fastapi-template")
except PackageNotFoundError:
    _APP_VERSION = "0.0.0"


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


async def _check_database(db: SessionDep) -> CheckResult:
    started_at = time.perf_counter()
    try:
        await asyncio.wait_for(
            db.execute(text("SELECT 1")), timeout=_CHECK_TIMEOUT_SECONDS
        )
    except TimeoutError:
        logger.warning("Health check: database ping timed out")
        return CheckResult(status="timeout")
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Health check: database ping failed: %s", exc)
        return CheckResult(status="unavailable")
    return CheckResult(status="ok", latency_ms=_elapsed_ms(started_at))


async def _check_redis() -> CheckResult:
    started_at = time.perf_counter()
    try:
        client = get_redis()
        await asyncio.wait_for(client.ping(), timeout=_CHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("Health check: redis ping timed out")
        return CheckResult(status="timeout")
    except (RedisError, RuntimeError, OSError) as exc:
        logger.warning("Health check: redis ping failed: %s", exc)
        return CheckResult(status="unavailable")
    return CheckResult(status="ok", latency_ms=_elapsed_ms(started_at))


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Liveness probe. Returns 200 as long as the process is running."""
    return LivenessResponse(version=_APP_VERSION)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(db: SessionDep, response: Response) -> ReadinessResponse:
    """Readiness probe. Pings critical dependencies and returns 503 if any fail."""
    database_check, redis_check = await asyncio.gather(
        _check_database(db),
        _check_redis(),
    )
    checks = {"database": database_check, "redis": redis_check}
    all_ok = all(check.status == "ok" for check in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if all_ok else "not_ready",
        version=_APP_VERSION,
        checks=checks,
    )
