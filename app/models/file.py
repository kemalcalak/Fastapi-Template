import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.utils import utc_now

if TYPE_CHECKING:
    from app.models.user import User


class File(Base):
    """Uploaded file metadata; the binary itself lives in Cloudinary.

    Generic across features: consumers (avatar, gallery, posts, ...) point at
    a File through their own ``file_id`` column rather than File referencing
    them. ``uploaded_by_id`` records who uploaded it (audit + ownership checks)
    but is nullable with ON DELETE SET NULL, so a file outlives its uploader.
    """

    __tablename__ = "file"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        index=True,
        default=None,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    public_id: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), default=None)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    # Logical bucket + Cloudinary sub-folder name. server_default backfills
    # existing rows as "general" so the NOT NULL column adds cleanly; indexed
    # for admin filtering and per-category cleanup queries.
    category: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default="general",
        default="general",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Uploader identity, surfaced in the admin file views for auditing and
    # name/email search. Loaded explicitly via ``selectinload`` in the admin
    # file repository; the default lazy keeps the upload path and public avatar
    # serialization single-query (they never read this relationship).
    uploaded_by: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[uploaded_by_id],
    )
