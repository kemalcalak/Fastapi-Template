import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, WebSocket

from app.api.deps import CurrentActiveUser, SessionDep, get_ws_user
from app.core.rate_limit import rate_limit_authenticated
from app.core.realtime import notifications_topic, serve_account_socket
from app.schemas.notification import (
    NotificationListResponse,
    NotificationReadResponse,
    NotificationsMarkAllReadResponse,
    UnreadCountResponse,
)
from app.services.notification_service import (
    list_my_notifications_service,
    mark_all_read_service,
    mark_read_service,
    unread_count_service,
)

router = APIRouter()

# Same semantics as the support socket: auth fails before the handshake
# completes, so we refuse with 1008 (Policy Violation) without accepting.
_WS_POLICY_VIOLATION = 1008


@router.get("", response_model=NotificationListResponse)
async def list_my_notifications(
    _request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    unread_only: Annotated[bool, Query()] = False,
) -> NotificationListResponse:
    """List the caller's notifications, newest first."""
    return await list_my_notifications_service(
        session=session,
        user=current_user,
        skip=skip,
        limit=limit,
        unread_only=unread_only,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    _request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
) -> UnreadCountResponse:
    """Return the caller's unread notification count (bell badge)."""
    return await unread_count_service(session=session, user=current_user)


@router.post("/read-all", response_model=NotificationsMarkAllReadResponse)
@rate_limit_authenticated("20/minute")
async def mark_all_notifications_read(
    request: Request,  # noqa: ARG001 - slowapi resolves the limit key by this name
    session: SessionDep,
    current_user: CurrentActiveUser,
) -> NotificationsMarkAllReadResponse:
    """Mark every unread notification of the caller as read."""
    return await mark_all_read_service(session=session, user=current_user)


@router.post("/{notification_id}/read", response_model=NotificationReadResponse)
@rate_limit_authenticated("60/minute")
async def mark_notification_read(
    request: Request,  # noqa: ARG001 - slowapi resolves the limit key by this name
    session: SessionDep,
    current_user: CurrentActiveUser,
    notification_id: uuid.UUID,
) -> NotificationReadResponse:
    """Mark one of the caller's notifications as read."""
    return await mark_read_service(
        session=session, user=current_user, notification_id=notification_id
    )


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket, session: SessionDep) -> None:
    """Live notification feed for the authenticated user.

    Authenticates from the ``access_token`` cookie and subscribes the socket to
    the caller's ``notifications:{id}`` topic. The client sends nothing; new
    notifications arrive as ``NotificationRealtimeEvent`` frames.
    """
    user = await get_ws_user(websocket, session)
    if user is None:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    await serve_account_socket(websocket, topic=notifications_topic(user.id))
