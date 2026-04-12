import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.utils import utc_now


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Get a single user by their UUID. Excludes deleted users."""
    user = await session.get(User, user_id)
    if user and user.is_deleted:
        return None
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Get a single user by their email address. Excludes deleted users."""
    statement = (
        select(User).where(User.email == email).where(User.is_deleted.is_(False))
    )
    result = await session.execute(statement)
    return result.scalars().first()


async def get_users_with_count(
    session: AsyncSession, skip: int = 0, limit: int = 100
) -> tuple[Sequence[User], int]:
    """Get paginated users and total count. Excludes deleted users."""
    count_statement = (
        select(func.count()).select_from(User).where(User.is_deleted.is_(False))
    )
    count_result = await session.execute(count_statement)
    count = count_result.scalar_one()

    users_statement = (
        select(User).where(User.is_deleted.is_(False)).offset(skip).limit(limit)
    )
    users_result = await session.execute(users_statement)
    users = users_result.scalars().all()
    return users, count


async def create_user(session: AsyncSession, user: User) -> User:
    """Create a new user in the database."""
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(session: AsyncSession, db_user: User, update_data: dict) -> User:
    """Update an existing user's data."""
    for key, value in update_data.items():
        setattr(db_user, key, value)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def soft_delete_user(session: AsyncSession, user: User) -> None:
    """Mark a user as deleted without physical removal."""
    user.is_deleted = True
    user.deleted_at = utc_now()
    user.is_active = False
    session.add(user)
    await session.commit()


async def deactivate_user(session: AsyncSession, user: User, grace_days: int) -> User:
    """Start the deactivation grace window for a user.

    Sets ``is_active=False`` and schedules hard deletion ``grace_days`` in the
    future. The row is locked with ``SELECT ... FOR UPDATE`` to guard against
    concurrent deactivate/reactivate requests on the same account.
    """
    locked = await session.execute(
        select(User).where(User.id == user.id).with_for_update()
    )
    db_user = locked.scalars().one()

    now = utc_now()
    db_user.is_active = False
    db_user.deactivated_at = now
    db_user.deletion_scheduled_at = now + timedelta(days=grace_days)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def reactivate_user(session: AsyncSession, user: User) -> User:
    """Cancel a pending deletion and re-enable the account."""
    locked = await session.execute(
        select(User).where(User.id == user.id).with_for_update()
    )
    db_user = locked.scalars().one()

    db_user.is_active = True
    db_user.deactivated_at = None
    db_user.deletion_scheduled_at = None
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def get_users_due_for_deletion(
    session: AsyncSession, now: datetime, limit: int
) -> Sequence[User]:
    """Return users whose grace period has elapsed, locked for this worker.

    Uses ``FOR UPDATE SKIP LOCKED`` so multiple workers can run the deletion
    job in parallel without colliding on the same rows.
    """
    statement = (
        select(User)
        .where(
            User.is_deleted.is_(False),
            User.deletion_scheduled_at.is_not(None),
            User.deletion_scheduled_at <= now,
        )
        .order_by(User.deletion_scheduled_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    result = await session.execute(statement)
    return result.scalars().all()


async def hard_delete_user(session: AsyncSession, user: User) -> None:
    """Permanently remove a user. Child rows cascade at the DB level."""
    await session.delete(user)
    await session.commit()


async def bulk_hard_delete_users(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> int:
    """Delete many users in a single SQL statement.

    Relies on the ``ON DELETE CASCADE`` foreign key from ``user_activity``
    so no ORM-level fan-out is required. Returns the number of rows removed.
    The caller owns the transaction boundary.
    """
    if not user_ids:
        return 0
    result = await session.execute(delete(User).where(User.id.in_(list(user_ids))))
    return result.rowcount or 0


async def delete_user(session: AsyncSession, db_user: User) -> None:
    """Hard-delete a user and commit. Caller owns the detach before calling."""
    await session.delete(db_user)
    await session.commit()
