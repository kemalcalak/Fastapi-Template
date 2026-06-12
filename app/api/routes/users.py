import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, WebSocket

from app.api.decorators import audit_unexpected_failure
from app.api.deps import (
    CurrentActiveUser,
    CurrentSessionId,
    CurrentUser,
    SessionDep,
    get_ws_user,
)
from app.core.config import settings
from app.core.messages.success_message import SuccessMessages
from app.core.rate_limit import rate_limit_strict
from app.core.realtime import account_topic, serve_account_socket
from app.schemas.msg import Message
from app.schemas.user import (
    DeleteAccount,
    UserMe,
    UserUpdateMe,
    UserUpdateResponse,
)
from app.schemas.user_activity import ActivityType, ResourceType
from app.schemas.user_session import SessionListResponse, SessionsRevokedResponse
from app.services.session_service import (
    list_my_sessions_service,
    revoke_my_other_sessions_service,
    revoke_my_session_service,
)
from app.services.user_service import (
    build_user_me_service,
    deactivate_own_account_service,
    reactivate_own_account_service,
    update_user_service,
)

router = APIRouter()


@router.get("/me", response_model=UserMe)
async def read_user_me(current_user: CurrentUser, session: SessionDep) -> UserMe:
    """Get current user; admins also receive their RBAC permissions."""
    return await build_user_me_service(session=session, user=current_user)


# WebSocket close code for a failed auth gate (RFC 6455 Policy Violation).
_WS_POLICY_VIOLATION = 1008


@router.websocket("/me/events")
async def account_events_ws(websocket: WebSocket, session: SessionDep) -> None:
    """Per-user notification socket for live account changes (e.g. RBAC perms).

    Authenticates the cookie; on success the socket joins the caller's account
    topic and receives events such as ``permissions_updated`` so the client can
    refetch ``/users/me`` immediately.
    """
    user = await get_ws_user(websocket, session)
    if user is None:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return
    await serve_account_socket(websocket, topic=account_topic(user.id))


@router.get("/me/sessions", response_model=SessionListResponse)
async def list_my_sessions(
    session: SessionDep,
    current_user: CurrentActiveUser,
    current_session_id: CurrentSessionId,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SessionListResponse:
    """List the caller's active sessions, flagging the current device."""
    return await list_my_sessions_service(
        session,
        user=current_user,
        current_session_id=current_session_id,
        skip=skip,
        limit=limit,
    )


@router.delete("/me/sessions", response_model=SessionsRevokedResponse)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.AUTH,
    endpoint="/users/me/sessions (revoke others)",
)
async def revoke_my_other_sessions(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    current_session_id: CurrentSessionId,
) -> SessionsRevokedResponse:
    """Log the caller out of every device except the one making this request."""
    return await revoke_my_other_sessions_service(
        request, session, user=current_user, current_session_id=current_session_id
    )


@router.delete("/me/sessions/{session_id}", response_model=Message)
@rate_limit_strict("10/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.AUTH,
    endpoint="/users/me/sessions/{id}",
)
async def revoke_my_session(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    session_id: uuid.UUID,
) -> Message:
    """Revoke a single session of the caller (remote logout for one device)."""
    return await revoke_my_session_service(
        request, session, user=current_user, session_id=session_id
    )


@router.patch("/me", response_model=UserUpdateResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/users/me",
)
async def update_user_me(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    user_in: UserUpdateMe,
) -> UserUpdateResponse:
    """Update own user details."""
    updated_user = await update_user_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=current_user.id,
        user_update=user_in,
    )
    return UserUpdateResponse(user=updated_user, message=SuccessMessages.USER_UPDATED)


@router.delete("/me", response_model=Message)
@rate_limit_strict("3/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/users/me (deactivate)",
)
async def delete_user_me(
    request: Request,
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
    body: DeleteAccount,
) -> Message:
    """Deactivate own account and schedule hard deletion after grace days.

    The account is not removed immediately — ``ACCOUNT_DELETION_GRACE_DAYS``
    later, the arq worker performs the irreversible delete. The user may
    cancel the deletion via ``POST /users/me/reactivate`` before that.
    The caller's auth cookies are cleared and their tokens revoked.
    """
    result = await deactivate_own_account_service(
        request=request,
        session=session,
        current_user=current_user,
        password=body.password,
        lang=body.lang,
    )
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(
        key="refresh_token", path=f"{settings.API_V1_STR}/auth/refresh"
    )
    return result


@router.post("/me/reactivate", response_model=Message)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/users/me/reactivate",
)
async def reactivate_user_me(
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    """Cancel a pending account deletion while still inside the grace window."""
    return await reactivate_own_account_service(
        request=request, session=session, current_user=current_user
    )
