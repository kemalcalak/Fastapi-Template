import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, WebSocket, status

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentActiveUser, SessionDep, get_ws_user
from app.core.rate_limit import rate_limit_authenticated, rate_limit_strict
from app.core.realtime import serve_multiplex, user_topic
from app.schemas.support import (
    MessageCreate,
    SupportMessageResponse,
    SupportTicketDetail,
    SupportTicketListResponse,
    SupportTicketResponse,
    TicketCreate,
    TicketStatus,
)
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.support_service import (
    can_user_access_ticket_service,
    close_ticket_service,
    create_ticket_service,
    get_my_ticket_service,
    list_my_tickets_service,
    reply_ticket_service,
)

router = APIRouter()

# Auth/ownership is checked before the handshake completes, so we close without
# accepting. The browser surfaces this as a generic HTTP 403 on the upgrade
# request — the WS close code is mainly server-side semantics. 1008 (Policy
# Violation, RFC 6455) is the standard code for refusing a socket on policy
# grounds; we use the one code for both "no/invalid auth" and "not the owner".
_WS_POLICY_VIOLATION = 1008


@router.post(
    "/tickets",
    response_model=SupportTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
@rate_limit_strict("10/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.CREATE,
    resource_type=ResourceType.SUPPORT_TICKET,
    endpoint="/support/tickets",
)
async def create_ticket(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    payload: TicketCreate,
) -> SupportTicketResponse:
    """Open a new support ticket with its first message."""
    return await create_ticket_service(
        session=session, user=current_user, payload=payload, request=request
    )


@router.get("/tickets", response_model=SupportTicketListResponse)
async def list_my_tickets(
    _request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> SupportTicketListResponse:
    """List the caller's own tickets, newest activity first."""
    return await list_my_tickets_service(
        session=session,
        user=current_user,
        skip=skip,
        limit=limit,
        status=status_filter.value if status_filter else None,
        search=search,
    )


@router.get("/tickets/{ticket_id}", response_model=SupportTicketDetail)
async def get_my_ticket(
    _request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    ticket_id: uuid.UUID,
) -> SupportTicketDetail:
    """Get one of the caller's tickets with its full message thread."""
    return await get_my_ticket_service(
        session=session, user=current_user, ticket_id=ticket_id
    )


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=SupportMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@rate_limit_authenticated("30/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.SUPPORT_TICKET,
    endpoint="/support/tickets/{ticket_id}/messages",
)
async def reply_ticket(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    ticket_id: uuid.UUID,
    payload: MessageCreate,
) -> SupportMessageResponse:
    """Append a reply to one of the caller's open tickets."""
    return await reply_ticket_service(
        session=session,
        user=current_user,
        ticket_id=ticket_id,
        payload=payload,
        request=request,
    )


@router.post("/tickets/{ticket_id}/close", response_model=SupportTicketResponse)
@rate_limit_authenticated("20/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.SUPPORT_TICKET,
    endpoint="/support/tickets/{ticket_id}/close",
)
async def close_ticket(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    ticket_id: uuid.UUID,
) -> SupportTicketResponse:
    """Close one of the caller's tickets."""
    return await close_ticket_service(
        session=session, user=current_user, ticket_id=ticket_id, request=request
    )


@router.websocket("/ws")
async def support_feed_ws(websocket: WebSocket, session: SessionDep) -> None:
    """One multiplexed socket per user: their feed plus any ticket they own.

    Authenticates from the ``access_token`` cookie, auto-subscribes to the
    caller's feed (``user:{id}``), then accepts ``subscribe``/``unsubscribe``
    frames for ``ticket:{id}`` threads they own. Replaces the old per-ticket
    socket so the whole session rides one connection.
    """
    user = await get_ws_user(websocket, session)
    if user is None:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    async def authorize(ticket_id: uuid.UUID) -> bool:
        return await can_user_access_ticket_service(
            session, user=user, ticket_id=ticket_id
        )

    await serve_multiplex(
        websocket, feed_topic=user_topic(user.id), authorize_ticket=authorize
    )
