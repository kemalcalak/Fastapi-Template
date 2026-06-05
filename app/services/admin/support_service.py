import logging
import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.support import SupportMessage, SupportTicket
from app.models.user import User
from app.repositories.admin.support import list_tickets_admin
from app.repositories.support import (
    add_message,
    attach_files,
    count_unread,
    get_message_with_attachments,
    get_ticket,
    get_ticket_with_thread,
    mark_thread_read,
    update_ticket,
)
from app.repositories.user import get_user_by_id
from app.schemas.support import (
    AdminTicketDetail,
    AdminTicketListItem,
    AdminTicketListResponse,
    AdminTicketUpdate,
    MessageCreate,
    SenderRole,
    SupportMessageRead,
    SupportMessageResponse,
    TicketStatus,
)
from app.schemas.user import SystemRole
from app.schemas.user_activity import ActivityType, ResourceType
from app.use_cases.log_activity import log_activity
from app.use_cases.support_attachments import resolve_attachment_files
from app.utils import utc_now

logger = logging.getLogger(__name__)


async def _load_ticket_or_404(
    session: AsyncSession, ticket_id: uuid.UUID
) -> SupportTicket:
    """Fetch a ticket by id or raise 404."""
    ticket = await get_ticket(session, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.TICKET_NOT_FOUND,
        )
    return ticket


async def _serialize_admin_detail(
    session: AsyncSession, ticket_id: uuid.UUID
) -> AdminTicketDetail:
    """Reload a ticket with thread and owner, mapped to the admin detail schema."""
    ticket = await get_ticket_with_thread(session, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.TICKET_NOT_FOUND,
        )
    return AdminTicketDetail.model_validate(ticket)


async def list_tickets_admin_service(
    session: AsyncSession,
    *,
    skip: int,
    limit: int,
    search: str | None,
    status: str | None,
    priority: str | None,
    assigned_admin_id: uuid.UUID | None,
) -> AdminTicketListResponse:
    """Return the filtered, paginated admin ticket queue with unread counts."""
    tickets, total = await list_tickets_admin(
        session,
        skip=skip,
        limit=limit,
        search=search,
        status=status,
        priority=priority,
        assigned_admin_id=assigned_admin_id,
    )
    items: list[AdminTicketListItem] = []
    for ticket in tickets:
        item = AdminTicketListItem.model_validate(ticket)
        item.unread_count = await count_unread(
            session, ticket_id=ticket.id, reader_role=SenderRole.ADMIN.value
        )
        items.append(item)
    return AdminTicketListResponse(data=items, total=total, skip=skip, limit=limit)


async def get_ticket_admin_service(
    session: AsyncSession, *, ticket_id: uuid.UUID
) -> AdminTicketDetail:
    """Return a ticket's full admin view, marking user messages as read."""
    await _load_ticket_or_404(session, ticket_id)
    await mark_thread_read(
        session, ticket_id=ticket_id, reader_role=SenderRole.ADMIN.value
    )
    return await _serialize_admin_detail(session, ticket_id)


async def reply_ticket_admin_service(
    session: AsyncSession,
    *,
    admin: User,
    ticket_id: uuid.UUID,
    payload: MessageCreate,
    request: Request | None = None,
) -> SupportMessageResponse:
    """Append an admin reply, self-assign if unassigned, await user response."""
    ticket = await _load_ticket_or_404(session, ticket_id)

    files = await resolve_attachment_files(
        session, file_ids=payload.attachment_file_ids, uploader_id=admin.id
    )
    message = SupportMessage(
        ticket_id=ticket.id,
        sender_id=admin.id,
        sender_role=SenderRole.ADMIN.value,
        body=payload.body,
    )
    message = await add_message(session, message)
    if files:
        await attach_files(session, message_id=message.id, files=files)

    update_data: dict = {"status": TicketStatus.PENDING.value}
    if ticket.assigned_admin_id is None:
        update_data["assigned_admin_id"] = admin.id
    await update_ticket(session, ticket, update_data)

    await log_activity(
        session=session,
        user_id=admin.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.SUPPORT_TICKET,
        resource_id=ticket.id,
        details={"action": "admin_replied"},
        request=request,
    )

    loaded = await get_message_with_attachments(session, message.id)
    return SupportMessageResponse(
        data=SupportMessageRead.model_validate(loaded),
        message=SuccessMessages.ADMIN_TICKET_REPLIED,
    )


async def update_ticket_admin_service(
    session: AsyncSession,
    *,
    admin: User,
    ticket_id: uuid.UUID,
    payload: AdminTicketUpdate,
    request: Request | None = None,
) -> AdminTicketDetail:
    """Change a ticket's status, priority, or assignment."""
    ticket = await _load_ticket_or_404(session, ticket_id)

    update_data = payload.model_dump(exclude_unset=True)

    if payload.assigned_admin_id is not None:
        assignee = await get_user_by_id(session, payload.assigned_admin_id)
        if assignee is None or assignee.role != SystemRole.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=ErrorMessages.INVALID_ASSIGNED_ADMIN,
            )

    # Keep ``closed_at`` consistent with the target status when it changes.
    if payload.status is not None:
        if payload.status == TicketStatus.CLOSED:
            update_data["closed_at"] = utc_now()
        else:
            update_data["closed_at"] = None

    if update_data:
        await update_ticket(session, ticket, update_data)

    await log_activity(
        session=session,
        user_id=admin.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.SUPPORT_TICKET,
        resource_id=ticket.id,
        details={"updated_fields": list(update_data.keys())},
        request=request,
    )

    return await _serialize_admin_detail(session, ticket_id)
