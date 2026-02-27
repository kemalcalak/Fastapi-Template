import uuid
from datetime import datetime
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.utils import utc_now


class TokenBlacklist(Base):
    """
    Stores revoked JWT tokens (specifically refresh tokens, or their JTIs).
    Allows preventing usage of tokens after logout or password changes.
    """
    __tablename__ = "token_blacklist"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
