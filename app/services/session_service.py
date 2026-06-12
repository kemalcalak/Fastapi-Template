import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.user import User
from app.repositories.user_session import (
    flag_sessions_revoked,
    get_session_by_id,
    list_active_sessions,
    revoke_all_sessions,
    revoke_session,
)
from app.schemas.msg import Message
from app.schemas.user_activity import ActivityType, ResourceType
from app.schemas.user_session import (
    SessionListResponse,
    SessionRead,
    SessionsRevokedResponse,
)
from app.use_cases.log_activity import log_activity
from app.utils import ensure_utc, utc_now


async def list_my_sessions_service(
    session: AsyncSession, *, user: User, current_session_id: uuid.UUID | None
) -> SessionListResponse:
    """Return the caller's live sessions with their own device flagged."""
    rows = await list_active_sessions(session, user_id=user.id)
    data = [
        SessionRead.from_model(row, current_session_id=current_session_id)
        for row in rows
    ]
    return SessionListResponse(data=data, total=len(data))


async def revoke_my_session_service(
    request: Request,
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
) -> Message:
    """Revoke one of the caller's sessions (their current one included).

    A session that does not exist, belongs to someone else, or is already
    revoked/expired uniformly yields 404 so the endpoint never confirms
    foreign session ids.
    """
    row = await get_session_by_id(session, session_id)
    if (
        row is None
        or row.user_id != user.id
        or row.revoked_at is not None
        or ensure_utc(row.expires_at) <= utc_now()
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.SESSION_NOT_FOUND,
        )

    await revoke_session(session, session_id=session_id)
    await flag_sessions_revoked([session_id])

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        details={"action": "session_revoked", "session_id": str(session_id)},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.SESSION_REVOKED)


async def revoke_my_other_sessions_service(
    request: Request,
    session: AsyncSession,
    *,
    user: User,
    current_session_id: uuid.UUID | None,
) -> SessionsRevokedResponse:
    """Revoke every session of the caller except the one making this request."""
    revoked = await revoke_all_sessions(
        session, user_id=user.id, except_session_id=current_session_id
    )
    if revoked:
        await flag_sessions_revoked([row.id for row in revoked])

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        details={"action": "other_sessions_revoked", "count": len(revoked)},
        request=request,
    )

    return SessionsRevokedResponse(
        revoked=len(revoked), message=SuccessMessages.OTHER_SESSIONS_REVOKED
    )
