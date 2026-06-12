import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.utils import utc_now

if TYPE_CHECKING:
    from app.models.user import User


class UserSession(Base):
    """A login session tied to one device/browser.

    The row's ``id`` is the ``sid`` claim embedded in both the access and the
    refresh token, so a revoked session can invalidate its access tokens
    without a DB lookup (Redis guard keyed by sid). ``refresh_jti`` always
    holds the jti of the *latest* refresh token issued for this session; on
    rotation it is overwritten, so a replayed (older) refresh token no longer
    matches and the whole session is revoked as compromised.
    """

    __tablename__ = "user_session"
    __table_args__ = (
        # "My active sessions, most recently used first".
        Index("ix_user_session_user_last_used", "user_id", "last_used_at"),
        # Purge job scan: expired rows are deleted regardless of revocation.
        Index("ix_user_session_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    # jti of the most recent refresh token issued for this session (rotates).
    refresh_jti: Mapped[str] = mapped_column(String(36), nullable=False)
    # Raw User-Agent header; parsed into browser/OS at the schema layer so no
    # migration is needed when the parsing heuristics improve.
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    # Text form, sized for IPv6.
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    # Bumped on every refresh rotation; powers "last active" in the UI.
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    # Mirrors the current refresh token's expiry; pushed forward on rotation.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Set on logout, manual revoke, or detected refresh-token replay.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    user: Mapped["User"] = relationship("User")
