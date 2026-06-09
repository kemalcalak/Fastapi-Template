"""Redis-backed store for the email-OTP root-superadmin transfer flow.

A pending transfer is keyed by the *current* root's id and holds the target
superadmin id plus a hash of the emailed OTP. Entries auto-expire via Redis TTL
so an unconfirmed transfer simply lapses.
"""

import hashlib
import json
import uuid

from app.core.redis import get_redis

_KEY_PREFIX = "root_transfer:"
# A pending transfer is dropped after this many wrong code submissions, forcing
# the root to restart the flow (defence-in-depth on top of endpoint rate limits).
_MAX_ATTEMPTS = 3


def _key(root_id: uuid.UUID) -> str:
    """Build the Redis key holding the pending transfer for a root superadmin."""
    return f"{_KEY_PREFIX}{root_id}"


def _hash_code(code: str) -> str:
    """Hash an OTP so the plaintext code is never persisted in Redis."""
    return hashlib.sha256(code.encode()).hexdigest()


async def store_root_transfer_otp(
    root_id: uuid.UUID,
    target_id: uuid.UUID,
    code: str,
    ttl_seconds: int,
) -> None:
    """Persist a pending transfer (target + hashed OTP + attempt counter)."""
    payload = json.dumps(
        {"target_id": str(target_id), "code_hash": _hash_code(code), "attempts": 0}
    )
    await get_redis().set(_key(root_id), payload, ex=ttl_seconds)


async def verify_root_transfer_otp(root_id: uuid.UUID, code: str) -> uuid.UUID | None:
    """Verify an OTP and return the pending target id on a match, else ``None``.

    A wrong code consumes one of ``_MAX_ATTEMPTS`` tries (the remaining TTL is
    preserved); once they are exhausted the pending transfer is dropped so the
    root must restart the flow. Missing, expired, wrong-code, and exhausted cases
    all return ``None`` so the response never reveals which one occurred.
    """
    redis = get_redis()
    key = _key(root_id)
    raw = await redis.get(key)
    if not raw:
        return None
    data = json.loads(raw)
    if data.get("code_hash") == _hash_code(code):
        return uuid.UUID(data["target_id"])

    attempts = int(data.get("attempts", 0)) + 1
    if attempts >= _MAX_ATTEMPTS:
        await redis.delete(key)
        return None
    data["attempts"] = attempts
    ttl = await redis.ttl(key)
    await redis.set(key, json.dumps(data), ex=ttl if ttl and ttl > 0 else None)
    return None


async def delete_root_transfer_otp(root_id: uuid.UUID) -> None:
    """Drop a pending transfer (after a successful confirm)."""
    await get_redis().delete(_key(root_id))
