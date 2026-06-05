import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.utils import utc_now

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.user import User


class SupportTicket(Base):
    """A support conversation opened by a user and handled by admins.

    ``status``/``priority`` are stored as plain strings (mirroring ``User.role``)
    and validated at the schema layer rather than via a DB enum, so adding a new
    status never requires an ``ALTER TYPE`` migration.
    """

    __tablename__ = "support_ticket"
    __table_args__ = (
        # User-facing listing: "my tickets, newest activity first".
        Index("ix_support_ticket_user_id", "user_id"),
        # Admin queue: filter by status, ordered by recent activity. The
        # composite index serves both the WHERE and the ORDER BY in one scan.
        Index("ix_support_ticket_status_last_message", "status", "last_message_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Ticket owner. CASCADE: deleting a user removes their tickets (and, via the
    # message cascade below, every message under them).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    # Admin currently owning the ticket. SET NULL so a ticket survives the
    # deletion/suspension of the admin who was assigned to it.
    assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        default=None,
    )
    # Denormalized timestamp of the latest message, kept in sync by the service
    # layer. Powers list ordering without a correlated MAX() subquery per row.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Ticket owner, surfaced in admin views and searchable by name/email.
    # foreign_keys is explicit because the table has two FKs to ``user``
    # (owner + assigned_admin); without it SQLAlchemy can't pick a side.
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
    )

    # passive_deletes=True defers the cascade to the FK's ON DELETE CASCADE, so
    # deleting a ticket is one DELETE rather than one-per-message.
    messages: Mapped[list["SupportMessage"]] = relationship(
        "SupportMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupportMessage.created_at",
    )


class SupportMessage(Base):
    """A single message inside a support ticket, from either side."""

    __tablename__ = "support_message"
    __table_args__ = (
        # Loading a ticket fetches its messages oldest-first by this index.
        Index("ix_support_message_ticket_created", "ticket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_ticket.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Author. SET NULL keeps the message readable after the sender is deleted;
    # ``sender_role`` below preserves which side wrote it regardless.
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        default=None,
    )
    # Denormalized "user" / "admin" so the UI can align the bubble and the
    # service can reason about direction without re-resolving sender_id (which
    # may be NULL after account deletion).
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Set when the *other* side first reads the message; powers unread counts.
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    ticket: Mapped["SupportTicket"] = relationship(
        "SupportTicket", back_populates="messages"
    )
    attachments: Mapped[list["SupportMessageAttachment"]] = relationship(
        "SupportMessageAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class SupportMessageAttachment(Base):
    """Join row binding an uploaded ``File`` to a support message.

    The binary lives in the generic file/storage subsystem; this table only
    records the association so a message can carry zero or more attachments.
    """

    __tablename__ = "support_message_attachment"
    __table_args__ = (
        # A given file is attached to a message at most once.
        UniqueConstraint(
            "message_id", "file_id", name="uq_support_attachment_message_file"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_message.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # CASCADE: removing the underlying file drops its attachment rows. The file
    # subsystem owns lifecycle; this table never outlives its file.
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("file.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    message: Mapped["SupportMessage"] = relationship(
        "SupportMessage", back_populates="attachments"
    )
    # selectin so attachment file metadata loads (batched) alongside messages
    # and is safe to serialize in the async response path.
    file: Mapped["File"] = relationship("File", lazy="selectin")
