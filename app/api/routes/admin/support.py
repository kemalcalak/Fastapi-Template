import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect, status

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentSuperUser, SessionDep, get_ws_user
from app.core.rate_limit import rate_limit_authenticated
from app.core.realtime import manager
from app.schemas.support import (
    AdminTicketDetail,
    AdminTicketListResponse,
    AdminTicketUpdate,
    MessageCreate,
    SupportMessageResponse,
    TicketPriority,
    TicketStatus,
)
from app.schemas.user import SystemRole
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.support_service import (
    get_ticket_admin_service,
    list_tickets_admin_service,
    reply_ticket_admin_service,
    ticket_exists_service,
    update_ticket_admin_service,
)

router = APIRouter()

# Admin WS gates run before the handshake completes, so we close without
# accepting and the browser sees a generic HTTP 403 on the upgrade request. The
# WS close code is mainly server-side semantics. 1008 (Policy Violation, RFC
# 6455) is the standard "refused on policy grounds" code, used here for both a
# failed admin auth check and a request for a non-existent ticket.
_WS_POLICY_VIOLATION = 1008


@router.get("/tickets", response_model=AdminTicketListResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.SUPPORT_TICKET,
    endpoint="/admin/support/tickets",
)
async def list_tickets(
    _request: Request,
    _admin: CurrentSuperUser,
    session: SessionDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    search: Annotated[str | None, Query(max_length=255)] = None,
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: TicketPriority | None = None,
    assigned_admin_id: uuid.UUID | None = None,
) -> AdminTicketListResponse:
    """List all tickets for the admin queue with filters and pagination."""
    return await list_tickets_admin_service(
        session=session,
        skip=skip,
        limit=limit,
        search=search,
        status=status_filter.value if status_filter else None,
        priority=priority.value if priority else None,
        assigned_admin_id=assigned_admin_id,
    )


@router.get("/tickets/{ticket_id}", response_model=AdminTicketDetail)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.SUPPORT_TICKET,
    endpoint="/admin/support/tickets/{ticket_id}",
)
async def get_ticket(
    _request: Request,
    _admin: CurrentSuperUser,
    session: SessionDep,
    ticket_id: uuid.UUID,
) -> AdminTicketDetail:
    """Get a ticket's full admin view, marking user messages as read."""
    return await get_ticket_admin_service(session=session, ticket_id=ticket_id)


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=SupportMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@rate_limit_authenticated("60/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.SUPPORT_TICKET,
    endpoint="/admin/support/tickets/{ticket_id}/messages",
)
async def reply_ticket(
    request: Request,
    admin: CurrentSuperUser,
    session: SessionDep,
    ticket_id: uuid.UUID,
    payload: MessageCreate,
) -> SupportMessageResponse:
    """Reply to a ticket as an admin (self-assigns when unassigned)."""
    return await reply_ticket_admin_service(
        session=session,
        admin=admin,
        ticket_id=ticket_id,
        payload=payload,
        request=request,
    )


@router.patch("/tickets/{ticket_id}", response_model=AdminTicketDetail)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.SUPPORT_TICKET,
    endpoint="/admin/support/tickets/{ticket_id}",
)
async def update_ticket(
    request: Request,
    admin: CurrentSuperUser,
    session: SessionDep,
    ticket_id: uuid.UUID,
    payload: AdminTicketUpdate,
) -> AdminTicketDetail:
    """Change a ticket's status, priority, or admin assignment."""
    return await update_ticket_admin_service(
        session=session,
        admin=admin,
        ticket_id=ticket_id,
        payload=payload,
        request=request,
    )


async def _accept_admin_ws(websocket: WebSocket, session: SessionDep) -> bool:
    """Authenticate a WebSocket as an admin, closing it on failure.

    Returns True only when the cookie resolves to an active admin; otherwise the
    socket is closed with 4401 and False is returned.
    """
    user = await get_ws_user(websocket, session)
    if user is None or user.role != SystemRole.ADMIN.value:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return False
    return True


@router.websocket("/ws")
async def admin_feed_ws(websocket: WebSocket, session: SessionDep) -> None:
    """Stream the global admin feed: new tickets and status changes."""
    if not await _accept_admin_ws(websocket, session):
        return

    topic = "admin"
    await websocket.accept()
    await manager.connect(topic, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(topic, websocket)


@router.websocket("/tickets/{ticket_id}/ws")
async def admin_ticket_ws(
    websocket: WebSocket, ticket_id: uuid.UUID, session: SessionDep
) -> None:
    """Stream realtime events for a single ticket as an admin."""
    if not await _accept_admin_ws(websocket, session):
        return
    if not await ticket_exists_service(session, ticket_id):
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    topic = f"ticket:{ticket_id}"
    await websocket.accept()
    await manager.connect(topic, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(topic, websocket)
