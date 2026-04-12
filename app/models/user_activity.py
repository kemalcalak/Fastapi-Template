import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.user import User

from app.core.db import Base
from app.schemas.common import ActivityDetails
from app.schemas.user_activity import ActivityStatus
from app.utils import utc_now


class UserActivity(Base):
    """
    Model to track user activities and audit logs.
    """

    __tablename__ = "user_activity"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Enums stored as strings
    activity_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String, nullable=False, index=True)

    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), default=None, index=True
    )

    details: Mapped[ActivityDetails] = mapped_column(JSON, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(
        String, default=ActivityStatus.SUCCESS.value, nullable=False
    )

    ip_address: Mapped[str | None] = mapped_column(String, default=None)
    user_agent: Mapped[str | None] = mapped_column(String, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="activities")
