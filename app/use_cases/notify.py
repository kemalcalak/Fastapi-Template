"""Cross-cutting helper to emit a persistent in-app notification.

Lives in ``use_cases/`` (not the notification service) so any domain service —
support, admin, files — can emit notifications without a service-to-service
call, mirroring ``log_activity``.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime import notifications_topic, publish_safe
from app.models.notification import Notification
from app.repositories.notification import create_notification
from app.schemas.common import JsonValue
from app.schemas.notification import (
    NotificationEventType,
    NotificationRead,
    NotificationRealtimeEvent,
    NotificationType,
)


async def notify(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: NotificationType,
    data: dict[str, JsonValue] | None = None,
) -> Notification:
    """Persist a notification for ``user_id`` and push it over their feed.

    The database row is the source of truth; the realtime publish is
    best-effort (``publish_safe``), so an offline user simply finds the
    notification in their inbox on the next fetch.
    """
    notification = Notification(
        user_id=user_id,
        type=type.value,
        data=data or {},
    )
    notification = await create_notification(session, notification)

    await publish_safe(
        notifications_topic(user_id),
        NotificationRealtimeEvent(
            type=NotificationEventType.NOTIFICATION_CREATED,
            notification=NotificationRead.model_validate(notification),
        ),
    )
    return notification
