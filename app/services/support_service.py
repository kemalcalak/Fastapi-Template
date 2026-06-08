import logging
import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.realtime import publish_feeds, publish_safe
from app.models.support import SupportMessage, SupportTicket
from app.models.user import User
from app.repositories.support import (
    add_message,
    attach_files,
    count_unread,
    count_unread_by_tickets,
    create_ticket,
    get_message_with_attachments,
    get_ticket,
    get_ticket_with_thread,
    list_user_tickets,
    mark_thread_read,
    update_ticket,
)
from app.schemas.file import FileCategory
from app.schemas.support import (
    AdminTicketListItem,
    MessageCreate,
    RealtimeEvent,
    RealtimeEventType,
    SenderRole,
    SupportMessageRead,
    SupportMessageResponse,
    SupportTicketDetail,
    SupportTicketListItem,
    SupportTicketListResponse,
    SupportTicketResponse,
    SupportTicketUser,
    TicketCreate,
    TicketStatus,
)
from app.schemas.user_activity import ActivityType, ResourceType
from app.use_cases.log_activity import log_activity
from app.use_cases.support_attachments import resolve_attachment_files
from app.utils import utc_now

logger = logging.getLogger(__name__)


async def _load_owned_ticket(
    session: AsyncSession, *, ticket_id: uuid.UUID, user: User
) -> SupportTicket:
    """Fetch a ticket and assert the caller owns it, else raise 404/403."""
    ticket = await get_ticket(session, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.TICKET_NOT_FOUND,
        )
    if ticket.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.TICKET_ACCESS_DENIED,
        )
    return ticket


async def _serialize_detail(
    session: AsyncSession, ticket_id: uuid.UUID
) -> SupportTicketDetail:
    """Reload a ticket with its full thread and map it to the detail schema."""
    ticket = await get_ticket_with_thread(session, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.TICKET_NOT_FOUND,
        )
    return SupportTicketDetail.model_validate(ticket)


async def _admin_summary(
    session: AsyncSession, ticket: SupportTicket, owner: User
) -> AdminTicketListItem:
    """Build the admin-queue summary row pushed over the ``admin`` feed."""
    unread = await count_unread(
        session, ticket_id=ticket.id, reader_role=SenderRole.ADMIN.value
    )
    return AdminTicketListItem(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        last_message_at=ticket.last_message_at,
        created_at=ticket.created_at,
        closed_at=ticket.closed_at,
        assigned_admin_id=ticket.assigned_admin_id,
        user=SupportTicketUser(
            id=owner.id,
            email=owner.email,
            first_name=owner.first_name,
            last_name=owner.last_name,
        ),
        unread_count=unread,
    )


async def can_user_access_ticket_service(
    session: AsyncSession, *, user: User, ticket_id: uuid.UUID
) -> bool:
    """Return whether ``user`` owns the ticket — the gate for its WebSocket."""
    ticket = await get_ticket(session, ticket_id)
    return ticket is not None and ticket.user_id == user.id


async def create_ticket_service(
    session: AsyncSession,
    *,
    user: User,
    payload: TicketCreate,
    request: Request | None = None,
) -> SupportTicketResponse:
    """Open a new ticket with its first message and optional attachments."""
    files = await resolve_attachment_files(
        session,
        file_ids=payload.attachment_file_ids,
        uploader_id=user.id,
        expected_category=FileCategory.SUPPORT_ATTACHMENT,
    )

    ticket = SupportTicket(
        user_id=user.id,
        subject=payload.subject,
        status=TicketStatus.OPEN.value,
    )
    ticket = await create_ticket(session, ticket)

    message = SupportMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        sender_role=SenderRole.USER.value,
        body=payload.body,
    )
    message = await add_message(session, message)
    if files:
        await attach_files(session, message_id=message.id, files=files)
        # Drop the freshly-created message's empty attachments collection from
        # the identity map so the reload below loads the rows we just added.
        session.expire(message, ["attachments"])

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.CREATE,
        resource_type=ResourceType.SUPPORT_TICKET,
        resource_id=ticket.id,
        details={"subject": payload.subject},
        request=request,
    )

    summary = await _admin_summary(session, ticket, user)
    await publish_feeds(
        ticket.user_id,
        RealtimeEvent(
            type=RealtimeEventType.TICKET_CREATED,
            ticket_id=ticket.id,
            ticket=summary,
        ),
    )

    detail = await _serialize_detail(session, ticket.id)
    return SupportTicketResponse(ticket=detail, message=SuccessMessages.TICKET_CREATED)


async def list_my_tickets_service(
    session: AsyncSession,
    *,
    user: User,
    skip: int,
    limit: int,
    status: str | None,
    search: str | None = None,
) -> SupportTicketListResponse:
    """Return the caller's own tickets with per-ticket unread counts."""
    tickets, total = await list_user_tickets(
        session, user_id=user.id, skip=skip, limit=limit, status=status, search=search
    )
    unread = await count_unread_by_tickets(
        session,
        ticket_ids=[ticket.id for ticket in tickets],
        reader_role=SenderRole.USER.value,
    )
    items: list[SupportTicketListItem] = []
    for ticket in tickets:
        item = SupportTicketListItem.model_validate(ticket)
        item.unread_count = unread.get(ticket.id, 0)
        items.append(item)
    return SupportTicketListResponse(data=items, total=total, skip=skip, limit=limit)


async def get_my_ticket_service(
    session: AsyncSession, *, user: User, ticket_id: uuid.UUID
) -> SupportTicketDetail:
    """Return one of the caller's tickets, marking admin replies as read."""
    await _load_owned_ticket(session, ticket_id=ticket_id, user=user)
    await mark_thread_read(
        session, ticket_id=ticket_id, reader_role=SenderRole.USER.value
    )
    return await _serialize_detail(session, ticket_id)


async def reply_ticket_service(
    session: AsyncSession,
    *,
    user: User,
    ticket_id: uuid.UUID,
    payload: MessageCreate,
    request: Request | None = None,
) -> SupportMessageResponse:
    """Append a user reply to an open ticket and move it back to the queue."""
    ticket = await _load_owned_ticket(session, ticket_id=ticket_id, user=user)
    if ticket.status == TicketStatus.CLOSED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorMessages.TICKET_ALREADY_CLOSED,
        )

    files = await resolve_attachment_files(
        session,
        file_ids=payload.attachment_file_ids,
        uploader_id=user.id,
        expected_category=FileCategory.SUPPORT_ATTACHMENT,
    )
    message = SupportMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        sender_role=SenderRole.USER.value,
        body=payload.body,
    )
    message = await add_message(session, message)
    if files:
        await attach_files(session, message_id=message.id, files=files)
        session.expire(message, ["attachments"])

    # A user reply puts the ball back in the support team's court.
    await update_ticket(session, ticket, {"status": TicketStatus.PENDING.value})

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.SUPPORT_TICKET,
        resource_id=ticket.id,
        details={"action": "user_replied"},
        request=request,
    )

    loaded = await get_message_with_attachments(session, message.id)
    message_read = SupportMessageRead.model_validate(loaded)

    await publish_safe(
        f"ticket:{ticket.id}",
        RealtimeEvent(
            type=RealtimeEventType.MESSAGE_CREATED,
            ticket_id=ticket.id,
            message=message_read,
        ),
    )
    summary = await _admin_summary(session, ticket, user)
    await publish_feeds(
        ticket.user_id,
        RealtimeEvent(
            type=RealtimeEventType.TICKET_UPDATED,
            ticket_id=ticket.id,
            ticket=summary,
        ),
    )

    return SupportMessageResponse(
        data=message_read,
        message=SuccessMessages.TICKET_MESSAGE_SENT,
    )


async def close_ticket_service(
    session: AsyncSession,
    *,
    user: User,
    ticket_id: uuid.UUID,
    request: Request | None = None,
) -> SupportTicketResponse:
    """Close one of the caller's tickets."""
    ticket = await _load_owned_ticket(session, ticket_id=ticket_id, user=user)
    await update_ticket(
        session,
        ticket,
        {"status": TicketStatus.CLOSED.value, "closed_at": utc_now()},
    )

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.SUPPORT_TICKET,
        resource_id=ticket.id,
        details={"action": "closed_by_user"},
        request=request,
    )

    summary = await _admin_summary(session, ticket, user)
    await publish_safe(
        f"ticket:{ticket.id}",
        RealtimeEvent(type=RealtimeEventType.TICKET_UPDATED, ticket_id=ticket.id),
    )
    await publish_feeds(
        ticket.user_id,
        RealtimeEvent(
            type=RealtimeEventType.TICKET_UPDATED,
            ticket_id=ticket.id,
            ticket=summary,
        ),
    )

    detail = await _serialize_detail(session, ticket_id)
    return SupportTicketResponse(ticket=detail, message=SuccessMessages.TICKET_CLOSED)
