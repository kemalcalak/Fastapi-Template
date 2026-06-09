"""Redis-backed account-lockout counters for the login flow.

Failed logins are counted per email (hashed so raw addresses are never stored)
inside a rolling window. Once the threshold is hit the account is locked for a
fixed period via a separate key that Redis evicts automatically. This stops
distributed brute-force that the per-IP rate limit cannot, since the counter
follows the targeted account rather than the source address.
"""

import hashlib

from app.core.config import settings
from app.core.redis import get_redis

_FAIL_PREFIX = "login_fail:"
_LOCK_PREFIX = "login_lock:"


def _hash(email: str) -> str:
    """Hash a normalised email so plaintext addresses are never persisted."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _fail_key(email: str) -> str:
    """Redis key holding the failed-attempt counter for an email."""
    return f"{_FAIL_PREFIX}{_hash(email)}"


def _lock_key(email: str) -> str:
    """Redis key holding the active lock flag for an email."""
    return f"{_LOCK_PREFIX}{_hash(email)}"


async def is_login_locked(email: str) -> int:
    """Return the remaining lock TTL in seconds, or ``0`` if not locked."""
    ttl = await get_redis().ttl(_lock_key(email))
    return ttl if ttl and ttl > 0 else 0


async def register_failed_login(email: str) -> bool:
    """Record a failed login; lock the account when the threshold is reached.

    Returns ``True`` only on the attempt that *transitions* the account into a
    locked state, so the caller can fire a one-off notification. The counter is
    reset when the lock is set, so subsequent attempts are short-circuited by
    ``is_login_locked`` rather than re-triggering this path.
    """
    redis = get_redis()
    fail_key = _fail_key(email)

    count = await redis.incr(fail_key)
    if count == 1:
        await redis.expire(fail_key, settings.LOGIN_FAILED_ATTEMPT_WINDOW_SECONDS)

    if count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
        await redis.set(_lock_key(email), "1", ex=settings.LOGIN_LOCKOUT_SECONDS)
        await redis.delete(fail_key)
        return True

    return False


async def clear_login_attempts(email: str) -> None:
    """Drop the counter and any lock for an email (called on a successful login)."""
    await get_redis().delete(_fail_key(email), _lock_key(email))
