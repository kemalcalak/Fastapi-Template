import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.user_activity import UserActivity

from app.core.db import Base
from app.utils import utc_now


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        # Partial index so the deletion worker's scan skips active rows and
        # rows without a scheduled deletion. Declared here (not only in the
        # migration) so Alembic autogenerate doesn't keep proposing to drop it.
        Index(
            "ix_user_deletion_due",
            "deletion_scheduled_at",
            postgresql_where="is_active = false AND deletion_scheduled_at IS NOT NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    first_name: Mapped[str | None] = mapped_column(String(100), default=None)
    last_name: Mapped[str | None] = mapped_column(String(100), default=None)
    title: Mapped[str | None] = mapped_column(String(100), default=None)
    role: Mapped[str] = mapped_column(String(20), default="user")
    hashed_password: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # passive_deletes=True lets Postgres handle the cascade via the FK's
    # ON DELETE CASCADE — a single DELETE statement instead of one per row.
    activities: Mapped[list["UserActivity"]] = relationship(
        "UserActivity",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
