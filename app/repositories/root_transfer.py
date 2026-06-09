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
    """Persist a pending transfer (target + hashed OTP) with an expiry."""
    payload = json.dumps({"target_id": str(target_id), "code_hash": _hash_code(code)})
    await get_redis().set(_key(root_id), payload, ex=ttl_seconds)


async def get_root_transfer_target(root_id: uuid.UUID, code: str) -> uuid.UUID | None:
    """Return the pending target id iff a matching, unexpired OTP exists.

    Returns ``None`` when there is no pending transfer, it has expired, or the
    supplied code does not match — the caller maps all three to one error so the
    response never reveals which condition failed.
    """
    raw = await get_redis().get(_key(root_id))
    if not raw:
        return None
    data = json.loads(raw)
    if data.get("code_hash") != _hash_code(code):
        return None
    return uuid.UUID(data["target_id"])


async def delete_root_transfer_otp(root_id: uuid.UUID) -> None:
    """Drop a pending transfer (after a successful confirm)."""
    await get_redis().delete(_key(root_id))
