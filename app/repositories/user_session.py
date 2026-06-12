import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    session: AsyncSession, *, user_id: uuid.UUID
) -> Sequence[UserSession]:
    """Return a user's live sessions, most recently used first.

    A session is live when it has not been revoked and its refresh token has
    not expired yet. The per-user count is naturally bounded (one row per
    device), so no pagination is needed.
    """
    statement = (
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > utc_now(),
        )
        .order_by(UserSession.last_used_at.desc())
    )
    return (await session.execute(statement)).scalars().all()


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
