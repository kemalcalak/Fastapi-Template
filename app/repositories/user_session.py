import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis
from app.models.user_session import UserSession
from app.utils import utc_now


async def create_session(
    session: AsyncSession, user_session: UserSession
) -> UserSession:
    """Persist a new login session."""
    session.add(user_session)
    await session.commit()
    await session.refresh(user_session)
    return user_session


async def get_session_by_id(
    session: AsyncSession, session_id: uuid.UUID
) -> UserSession | None:
    """Get a single session row by id (the token ``sid`` claim)."""
    return await session.get(UserSession, session_id)


async def list_active_sessions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> tuple[Sequence[UserSession], int]:
    """Return a page of a user's live sessions plus the total count.

    A session is live when it has not been revoked and its refresh token has
    not expired yet. Most recently used first.
    """
    base_stmt = select(UserSession).where(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > utc_now(),
    )

    count_stmt = base_stmt.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = (await session.execute(count_stmt)).scalar_one()

    list_stmt = (
        base_stmt.order_by(UserSession.last_used_at.desc()).offset(skip).limit(limit)
    )
    rows = (await session.execute(list_stmt)).scalars().all()
    return rows, total


async def rotate_session_jti(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    refresh_jti: str,
    expires_at: datetime,
) -> None:
    """Record a refresh rotation: new jti, fresh expiry, bumped last-used.

    Set-based UPDATE so the rotation never races with a concurrent read of a
    possibly-expired ORM instance.
    """
    statement = (
        update(UserSession)
        .where(UserSession.id == session_id)
        .values(refresh_jti=refresh_jti, expires_at=expires_at, last_used_at=utc_now())
    )
    await session.execute(statement)
    await session.commit()


async def revoke_session(
    session: AsyncSession, *, session_id: uuid.UUID
) -> UserSession | None:
    """Stamp a session as revoked and return the updated row.

    The ``revoked_at IS NULL`` guard makes a double revoke idempotent (the
    original revocation time is kept). Returns ``None`` when no such session
    exists.
    """
    statement = (
        update(UserSession)
        .where(
            UserSession.id == session_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=utc_now())
    )
    await session.execute(statement)
    await session.commit()
    return await session.get(UserSession, session_id)


async def revoke_all_sessions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    except_session_id: uuid.UUID | None = None,
) -> Sequence[UserSession]:
    """Revoke every live session of a user and return the rows just revoked.

    ``except_session_id`` keeps the caller's own session alive ("log out other
    devices"). The revoked rows are returned so the service layer can also
    blacklist their refresh jtis and flag their sids in Redis.
    """
    conditions = [
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > utc_now(),
    ]
    if except_session_id is not None:
        conditions.append(UserSession.id != except_session_id)

    victims = (
        (await session.execute(select(UserSession).where(*conditions))).scalars().all()
    )
    if not victims:
        return []

    statement = (
        update(UserSession)
        .where(UserSession.id.in_([v.id for v in victims]))
        .values(revoked_at=utc_now())
    )
    await session.execute(statement)
    await session.commit()
    return victims


async def purge_stale_sessions(
    session: AsyncSession, *, revoked_retention_days: int = 30
) -> int:
    """Delete sessions that are expired or were revoked long ago.

    Recently revoked rows are kept for ``revoked_retention_days`` so the user
    can still see "logged out" history if the UI ever wants it; expired rows
    carry no value and are dropped immediately. Returns the rows deleted.
    """
    cutoff = utc_now() - timedelta(days=revoked_retention_days)
    statement = delete(UserSession).where(
        or_(
            UserSession.expires_at < utc_now(),
            UserSession.revoked_at < cutoff,
        )
    )
    result = await session.execute(statement)
    await session.commit()
    return result.rowcount


# ---------------------------------------------------------------------------
# Redis revoked-sid flags
#
# The DB row is the source of truth for the *refresh* flow (which loads it
# anyway), but checking the DB on every API request would be too costly. These
# flags let ``get_current_user`` kill the access tokens of a revoked session
# with a single Redis lookup. TTL = access-token lifetime: past that, every
# access token carrying the sid has expired on its own.
# ---------------------------------------------------------------------------

_REVOKED_SID_PREFIX = "revoked:session:"


def _revoked_key(session_id: str | uuid.UUID) -> str:
    """Build the Redis key flagging a revoked session id."""
    return f"{_REVOKED_SID_PREFIX}{session_id}"


async def flag_sessions_revoked(session_ids: Iterable[str | uuid.UUID]) -> None:
    """Flag sids in Redis so their live access tokens die immediately."""
    redis = get_redis()
    ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    async with redis.pipeline(transaction=False) as pipe:
        for session_id in session_ids:
            pipe.set(_revoked_key(session_id), "1", ex=ttl)
        await pipe.execute()


async def is_session_revoked(session_id: str | uuid.UUID) -> bool:
    """Return True if the session id has been flagged as revoked."""
    redis = get_redis()
    return bool(await redis.exists(_revoked_key(session_id)))
