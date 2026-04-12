from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool: ConnectionPool | None = None
_client: Redis | None = None


def _build_pool() -> ConnectionPool:
    """Create a new Redis connection pool from settings."""
    return ConnectionPool.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=50,
        health_check_interval=30,
    )


async def init_redis() -> Redis:
    """Initialize and return the shared Redis client."""
    global _pool, _client
    if _client is None:
        _pool = _build_pool()
        _client = Redis(connection_pool=_pool)
        await _client.ping()
    return _client


async def close_redis() -> None:
    """Close the shared Redis client and its pool."""
    global _pool, _client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def get_redis() -> Redis:
    """Return the shared Redis client. Raises if not initialized."""
    if _client is None:
        raise RuntimeError("Redis client is not initialized")
    return _client


def set_redis_for_testing(client: Redis | None) -> None:
    """Override the shared Redis client (test-only helper)."""
    global _client
    _client = client
