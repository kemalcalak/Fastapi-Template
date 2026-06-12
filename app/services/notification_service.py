import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.notification import Notification
from app.models.user import User
from app.repositories.notification import (
    count_unread,
    get_notification,
    list_notifications,
    mark_all_read,
    mark_read,
)
from app.schemas.notification import (
    NotificationListResponse,
    NotificationRead,
    NotificationReadResponse,
    NotificationsMarkAllReadResponse,
    UnreadCountResponse,
)


async def _load_owned_notification(
    session: AsyncSession, *, notification_id: uuid.UUID, user: User
) -> Notification:
    """Fetch a notification and assert the caller owns it, else raise 404/403."""
    notification = await get_notification(session, notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.NOTIFICATION_NOT_FOUND,
        )
    if notification.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.NOTIFICATION_ACCESS_DENIED,
        )
    return notification


async def list_my_notifications_service(
    session: AsyncSession,
    *,
    user: User,
    skip: int,
    limit: int,
    unread_only: bool = False,
) -> NotificationListResponse:
    """Return the caller's notifications, newest first."""
    notifications, total = await list_notifications(
        session, user_id=user.id, skip=skip, limit=limit, unread_only=unread_only
    )
    items = [NotificationRead.model_validate(n) for n in notifications]
    return NotificationListResponse(data=items, total=total, skip=skip, limit=limit)


async def unread_count_service(
    session: AsyncSession, *, user: User
) -> UnreadCountResponse:
    """Return the caller's unread notification count (badge counter)."""
    unread = await count_unread(session, user_id=user.id)
    return UnreadCountResponse(unread_count=unread)


async def mark_read_service(
    session: AsyncSession, *, user: User, notification_id: uuid.UUID
) -> NotificationReadResponse:
    """Mark one of the caller's notifications as read."""
    await _load_owned_notification(session, notification_id=notification_id, user=user)
    updated = await mark_read(session, notification_id=notification_id)
    if updated is None:
        # Deleted between the ownership check and the update — treat as gone.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.NOTIFICATION_NOT_FOUND,
        )
    return NotificationReadResponse(
        data=NotificationRead.model_validate(updated),
        message=SuccessMessages.NOTIFICATION_READ,
    )


async def mark_all_read_service(
    session: AsyncSession, *, user: User
) -> NotificationsMarkAllReadResponse:
    """Mark every unread notification of the caller as read."""
    updated = await mark_all_read(session, user_id=user.id)
    return NotificationsMarkAllReadResponse(
        updated=updated,
        message=SuccessMessages.NOTIFICATIONS_ALL_READ,
    )
