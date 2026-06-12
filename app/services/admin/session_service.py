import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.realtime import account_topic, publish_safe
from app.models.user import User
from app.repositories.user import get_user_by_id
from app.repositories.user_session import (
    flag_sessions_revoked,
    list_active_sessions,
    revoke_all_sessions,
)
from app.schemas.account import AccountEvent, AccountEventType
from app.schemas.user import SystemRole
from app.schemas.user_activity import ActivityType, ResourceType
from app.schemas.user_session import (
    SessionListResponse,
    SessionRead,
    SessionsRevokedResponse,
)
from app.use_cases.log_activity import log_activity


async def _load_target(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Fetch the target user or raise 404."""
    target = await get_user_by_id(session, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    return target


def _guard_superadmin_target(actor: User, target: User) -> None:
    """Only superadmins may touch a superadmin's sessions."""
    if (
        target.role == SystemRole.SUPERADMIN.value
        and actor.role != SystemRole.SUPERADMIN.value
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.INSUFFICIENT_PERMISSIONS,
        )


async def list_user_sessions_admin_service(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> SessionListResponse:
    """Return a page of a user's live sessions for the admin detail view.

    ``is_current`` is never set here — "current" is meaningful only to the
    session owner, not to the admin looking at the list.
    """
    await _load_target(session, user_id)
    rows, total = await list_active_sessions(
        session, user_id=user_id, skip=skip, limit=limit
    )
    data = [SessionRead.from_model(row, current_session_id=None) for row in rows]
    return SessionListResponse(data=data, total=total, skip=skip, limit=limit)


async def revoke_user_sessions_admin_service(
    request: Request,
    session: AsyncSession,
    *,
    current_user: User,
    user_id: uuid.UUID,
) -> SessionsRevokedResponse:
    """Terminate every live session of a user (admin remote logout).

    All of the target's devices lose their access tokens immediately via the
    Redis sid flags, and the account socket broadcasts ``sessions_revoked`` so
    open tabs drop to the login screen without waiting for the next request.
    """
    target = await _load_target(session, user_id)
    _guard_superadmin_target(current_user, target)

    revoked = await revoke_all_sessions(session, user_id=target.id)
    if revoked:
        await flag_sessions_revoked([row.id for row in revoked])
        await publish_safe(
            account_topic(target.id),
            AccountEvent(type=AccountEventType.SESSIONS_REVOKED),
        )

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={"action": "admin_revoked_sessions", "count": len(revoked)},
        request=request,
    )

    return SessionsRevokedResponse(
        revoked=len(revoked), message=SuccessMessages.ADMIN_SESSIONS_REVOKED
    )
