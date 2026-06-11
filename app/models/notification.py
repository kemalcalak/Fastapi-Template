import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.schemas.common import JsonValue
from app.utils import utc_now

if TYPE_CHECKING:
    from app.models.user import User


class Notification(Base):
    """A persistent in-app notification addressed to a single user.

    ``type`` is a stable machine code (e.g. ``support_ticket_replied``) that the
    frontend maps to a translated message; no human-readable text is stored so
    notifications render correctly in every locale. ``data`` carries the
    type-specific payload (ids, names) needed to build the message and link.
    """

    __tablename__ = "notification"
    __table_args__ = (
        # Inbox listing: "my notifications, newest first". The user_id prefix
        # also serves the unread-count query (WHERE user_id = ? AND read_at IS NULL).
        Index("ix_notification_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Recipient. CASCADE: deleting a user removes their notifications.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stored as a plain string (mirroring ``User.role``) and validated at the
    # schema layer, so adding a new notification type never needs a migration.
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    data: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    # Set when the user opens/acknowledges the notification; powers unread counts.
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    user: Mapped["User"] = relationship("User")
