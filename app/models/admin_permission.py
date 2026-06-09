import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.user import User

from app.core.db import Base
from app.utils import utc_now


class AdminPermission(Base):
    """A single RBAC permission grant tying an admin to one permission key.

    Rows exist only for plain ``admin`` accounts; superadmins bypass these
    grants entirely. The unique constraint keeps grants idempotent — an admin
    holds a given permission at most once.
    """

    __tablename__ = "admin_permission"
    __table_args__ = (
        UniqueConstraint("user_id", "permission", name="uq_admin_permission_user_perm"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    permission: Mapped[str] = mapped_column(String(50), nullable=False)
    # Who granted it (a superadmin). SET NULL keeps the grant if that superadmin
    # is later removed, so the audit trail degrades gracefully instead of
    # cascading the grant away.
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        default=None,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # The admin holding this grant. foreign_keys pins the join to user_id since
    # granted_by is a second FK into the same table.
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="permissions",
    )
