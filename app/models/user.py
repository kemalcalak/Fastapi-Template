import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.file import File
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
        # pg_trgm GIN indexes powering the admin user search. Without these,
        # ``col ILIKE '%foo%'`` degrades to a sequential scan on every query.
        Index(
            "ix_user_email_trgm",
            "email",
            postgresql_using="gin",
            postgresql_ops={"email": "gin_trgm_ops"},
        ),
        Index(
            "ix_user_first_name_trgm",
            "first_name",
            postgresql_using="gin",
            postgresql_ops={"first_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_user_last_name_trgm",
            "last_name",
            postgresql_using="gin",
            postgresql_ops={"last_name": "gin_trgm_ops"},
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
    # Admin-initiated permanent suspension. Distinct from user self-deactivation
    # (which sets deactivated_at + deletion_scheduled_at). Suspended rows are
    # never scheduled for deletion, so the deletion worker ignores them.
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Current avatar. use_alter breaks the User<->File circular FK so
    # metadata.create_all (SQLite tests) can order the tables.
    avatar_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "file.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_user_avatar_file_id",
        ),
        default=None,
    )

    # passive_deletes=True lets Postgres handle the cascade via the FK's
    # ON DELETE CASCADE — a single DELETE statement instead of one per row.
    activities: Mapped[list["UserActivity"]] = relationship(
        "UserActivity",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Avatar points at one File via the local avatar_file_id FK. selectin so
    # it loads (batched) on every User load — safe to serialize in async.
    avatar_file: Mapped["File | None"] = relationship(
        "File",
        foreign_keys=[avatar_file_id],
        lazy="selectin",
    )
