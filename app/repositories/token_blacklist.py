"""Redis-backed JWT blacklist.

Revoked tokens are stored under ``blacklist:jwt:{jti}`` with a TTL equal to
the token's remaining lifetime — Redis evicts them automatically when they
expire, so no cleanup job is required. Lookups are O(1) and safe to run
across any number of API replicas or worker processes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import jwt

from app.core.config import settings
from app.core.redis import get_redis
from app.utils import utc_now

logger = logging.getLogger(__name__)

_KEY_PREFIX = "blacklist:jwt:"
# Fallback TTL when a token's expiry cannot be parsed (should not happen
# with valid JWTs but we never want a revoked token to live forever).
_FALLBACK_TTL_SECONDS = 60 * 60 * 24 * settings.REFRESH_TOKEN_EXPIRE_DAYS


def _key(jti: str) -> str:
    """Build the Redis key for a given JWT id."""
    return f"{_KEY_PREFIX}{jti}"


def _extract_claims(token: str) -> tuple[str, int]:
    """Return (jti, remaining_ttl_seconds) for a token without verifying it.

    Signature verification is intentionally skipped — callers must have
    already validated the token (or are deliberately revoking an expired
    one). We only need the claims to choose a stable key and TTL.
    """
    try:
        payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
        )
    except jwt.PyJWTError:
        return token, _FALLBACK_TTL_SECONDS

    jti = str(payload.get("jti") or token)
    exp = payload.get("exp")
    if exp is None:
        return jti, _FALLBACK_TTL_SECONDS

    try:
        expires_at = datetime.fromtimestamp(float(exp), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return jti, _FALLBACK_TTL_SECONDS

    remaining = int((expires_at - utc_now()).total_seconds())
    if remaining <= 0:
        # Token already expired; still blacklist briefly to stop reuse in a
        # narrow clock-skew window but let Redis evict it quickly.
        return jti, 60
    return jti, remaining


async def add_token_to_blacklist(token: str) -> None:
    """Revoke a JWT by storing its jti in Redis until the token expires."""
    jti, ttl = _extract_claims(token)
    redis = get_redis()
    await redis.set(_key(jti), "1", ex=ttl)


async def is_token_blacklisted(token: str) -> bool:
    """Return True if the given JWT has been revoked."""
    jti, _ = _extract_claims(token)
    redis = get_redis()
    return bool(await redis.exists(_key(jti)))
