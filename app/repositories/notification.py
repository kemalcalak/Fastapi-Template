import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.utils import utc_now


async def create_notification(
    session: AsyncSession, notification: Notification
) -> Notification:
    """Persist a new notification."""
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return notification


async def get_notification(
    session: AsyncSession, notification_id: uuid.UUID
) -> Notification | None:
    """Get a single notification by id."""
    return await session.get(Notification, notification_id)


async def list_notifications(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False,
) -> tuple[Sequence[Notification], int]:
    """Return a user's notifications (newest first) plus total count."""
    base_stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        base_stmt = base_stmt.where(Notification.read_at.is_(None))

    count_stmt = base_stmt.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = (await session.execute(count_stmt)).scalar_one()

    list_stmt = (
        base_stmt.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
    )
    notifications = (await session.execute(list_stmt)).scalars().all()
    return notifications, total


async def count_unread(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Count a user's unread notifications (badge counter)."""
    statement = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    )
    return (await session.execute(statement)).scalar_one()


async def mark_read(
    session: AsyncSession, *, notification_id: uuid.UUID
) -> Notification | None:
    """Stamp a single notification as read and return the updated row.

    Set-based so it never touches possibly-expired ORM attributes; the
    ``read_at IS NULL`` guard makes it idempotent (the original read time is
    never overwritten). Returns ``None`` if the notification no longer exists.
    """
    statement = (
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=utc_now())
    )
    await session.execute(statement)
    await session.commit()
    return await session.get(Notification, notification_id)


async def mark_all_read(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Mark every unread notification of a user as read in one bulk UPDATE.

    A set-based UPDATE (rather than load-and-loop) because the inbox is
    unbounded; returns the number of rows updated.
    """
    statement = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=utc_now())
    )
    result = await session.execute(statement)
    await session.commit()
    return result.rowcount
