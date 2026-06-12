import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.user_session import UserSession
from app.utils.user_agent import parse_user_agent


class SessionRead(BaseModel):
    """One active login session as shown on the security screen.

    ``browser``/``os`` are parsed server-side from the stored User-Agent so
    every client renders the same labels without shipping a UA parser.
    """

    id: uuid.UUID
    browser: str | None = None
    os: str | None = None
    ip_address: str | None = None
    created_at: datetime
    last_used_at: datetime
    # True for the session the caller used to make this request.
    is_current: bool = False

    @classmethod
    def from_model(
        cls, user_session: UserSession, *, current_session_id: uuid.UUID | None
    ) -> "SessionRead":
        """Map an ORM row to the public shape, marking the caller's own session."""
        parsed = parse_user_agent(user_session.user_agent)
        return cls(
            id=user_session.id,
            browser=parsed.browser,
            os=parsed.os,
            ip_address=user_session.ip_address,
            created_at=user_session.created_at,
            last_used_at=user_session.last_used_at,
            is_current=user_session.id == current_session_id,
        )


class SessionListResponse(BaseModel):
    """The caller's active sessions, most recently used first."""

    data: list[SessionRead]
    total: int


class SessionsRevokedResponse(BaseModel):
    """Standard response after a bulk session revocation."""

    revoked: int
    message: str
