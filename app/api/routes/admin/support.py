import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, WebSocket, status

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentSuperUser, SessionDep, get_ws_user
from app.core.rate_limit import rate_limit_authenticated
from app.core.realtime import ADMIN_TOPIC, serve_multiplex
from app.schemas.support import (
    AdminTicketDetail,
    AdminTicketListResponse,
    AdminTicketResponse,
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


@router.patch("/tickets/{ticket_id}", response_model=AdminTicketResponse)
@rate_limit_authenticated("30/minute")
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
) -> AdminTicketResponse:
    """Change a ticket's status, priority, or admin assignment."""
    return await update_ticket_admin_service(
        session=session,
        admin=admin,
        ticket_id=ticket_id,
        payload=payload,
        request=request,
    )


@router.websocket("/ws")
async def admin_feed_ws(websocket: WebSocket, session: SessionDep) -> None:
    """One multiplexed socket per admin: the global queue plus any ticket thread.

    Authenticates the cookie as an active admin, auto-subscribes to the ``admin``
    feed, then accepts ``subscribe``/``unsubscribe`` frames for any existing
    ticket. Replaces the old per-ticket admin socket.
    """
    user = await get_ws_user(websocket, session)
    if user is None or user.role != SystemRole.ADMIN.value:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    async def authorize(ticket_id: uuid.UUID) -> bool:
        return await ticket_exists_service(session, ticket_id)

    await serve_multiplex(websocket, feed_topic=ADMIN_TOPIC, authorize_ticket=authorize)
