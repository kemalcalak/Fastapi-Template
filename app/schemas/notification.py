import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import JsonValue


class NotificationType(StrEnum):
    """Machine codes for notification kinds.

    Each value doubles as the frontend translation key, so adding a type means
    adding it here plus a locale entry — the database schema never changes.
    """

    SUPPORT_TICKET_REPLIED = "support_ticket_replied"
    SUPPORT_TICKET_STATUS_CHANGED = "support_ticket_status_changed"
    ADMIN_PERMISSIONS_CHANGED = "admin_permissions_changed"


class NotificationRead(BaseModel):
    """A single notification as returned to its recipient."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: NotificationType
    data: dict[str, JsonValue] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    """Paginated listing of the caller's notifications."""

    data: list[NotificationRead]
    total: int
    skip: int
    limit: int


class UnreadCountResponse(BaseModel):
    """Number of unread notifications for the caller (badge counter)."""

    unread_count: int


class NotificationReadResponse(BaseModel):
    """Standard response after marking a single notification as read."""

    data: NotificationRead
    message: str


class NotificationsMarkAllReadResponse(BaseModel):
    """Standard response after marking every unread notification as read."""

    updated: int
    message: str


# --- Realtime (WebSocket / Redis pub-sub) ----------------------------------


class NotificationEventType(StrEnum):
    """Kinds of events pushed over the notification WebSocket."""

    NOTIFICATION_CREATED = "notification_created"


class NotificationRealtimeEvent(BaseModel):
    """Envelope broadcast to a user's notification feed on new notifications."""

    type: NotificationEventType
    notification: NotificationRead
