import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.file import File
from app.models.support import (
    SupportMessage,
    SupportMessageAttachment,
    SupportTicket,
)
from app.utils import utc_now


async def get_ticket(
    session: AsyncSession, ticket_id: uuid.UUID
) -> SupportTicket | None:
    """Get a single ticket by id, without its message thread."""
    return await session.get(SupportTicket, ticket_id)


async def get_ticket_with_thread(
    session: AsyncSession, ticket_id: uuid.UUID
) -> SupportTicket | None:
    """Get a ticket eagerly loaded with its messages and their attachments."""
    statement = (
        select(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .options(
            selectinload(SupportTicket.user),
            selectinload(SupportTicket.assigned_admin),
            selectinload(SupportTicket.messages)
            .selectinload(SupportMessage.attachments)
            .selectinload(SupportMessageAttachment.file),
        )
    )
    result = await session.execute(statement)
    return result.scalars().first()


async def get_message_with_attachments(
    session: AsyncSession, message_id: uuid.UUID
) -> SupportMessage | None:
    """Get a single message eagerly loaded with its attachment files."""
    statement = (
        select(SupportMessage)
        .where(SupportMessage.id == message_id)
        .options(
            selectinload(SupportMessage.attachments).selectinload(
                SupportMessageAttachment.file
            )
        )
    )
    result = await session.execute(statement)
    return result.scalars().first()


async def list_user_tickets(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
) -> tuple[Sequence[SupportTicket], int]:
    """Return a user's own tickets (newest activity first) plus total count."""
    base_stmt = select(SupportTicket).where(SupportTicket.user_id == user_id)
    if status is not None:
        base_stmt = base_stmt.where(SupportTicket.status == status)

    count_stmt = base_stmt.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = (await session.execute(count_stmt)).scalar_one()

    list_stmt = (
        base_stmt.order_by(SupportTicket.last_message_at.desc())
        .offset(skip)
        .limit(limit)
    )
    tickets = (await session.execute(list_stmt)).scalars().all()
    return tickets, total


async def create_ticket(session: AsyncSession, ticket: SupportTicket) -> SupportTicket:
    """Persist a new ticket."""
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def add_message(session: AsyncSession, message: SupportMessage) -> SupportMessage:
    """Persist a message and bump its ticket's ``last_message_at``."""
    session.add(message)
    await session.flush()

    ticket = await session.get(SupportTicket, message.ticket_id)
    if ticket is not None:
        ticket.last_message_at = message.created_at

    await session.commit()
    await session.refresh(message)
    return message


async def update_ticket(
    session: AsyncSession, ticket: SupportTicket, update_data: dict[str, object]
) -> SupportTicket:
    """Apply a partial update to a ticket and persist it."""
    for key, value in update_data.items():
        setattr(ticket, key, value)
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def attach_files(
    session: AsyncSession, *, message_id: uuid.UUID, files: Sequence[File]
) -> None:
    """Bind already-validated files to a message as attachments."""
    for file in files:
        session.add(SupportMessageAttachment(message_id=message_id, file_id=file.id))
    await session.commit()


async def mark_thread_read(
    session: AsyncSession, *, ticket_id: uuid.UUID, reader_role: str
) -> int:
    """Mark unread messages written by the *other* side as read.

    ``reader_role`` is the side doing the reading; messages whose
    ``sender_role`` differs and are still unread get a ``read_at`` stamp.
    Returns the number of rows updated.
    """
    statement = select(SupportMessage).where(
        SupportMessage.ticket_id == ticket_id,
        SupportMessage.sender_role != reader_role,
        SupportMessage.read_at.is_(None),
    )
    messages = (await session.execute(statement)).scalars().all()
    if not messages:
        return 0

    now = utc_now()
    for message in messages:
        message.read_at = now
    await session.commit()
    return len(messages)


async def count_unread(
    session: AsyncSession, *, ticket_id: uuid.UUID, reader_role: str
) -> int:
    """Count messages from the other side that ``reader_role`` has not read."""
    statement = (
        select(func.count())
        .select_from(SupportMessage)
        .where(
            SupportMessage.ticket_id == ticket_id,
            SupportMessage.sender_role != reader_role,
            SupportMessage.read_at.is_(None),
        )
    )
    return (await session.execute(statement)).scalar_one()


async def count_unread_by_tickets(
    session: AsyncSession, *, ticket_ids: Sequence[uuid.UUID], reader_role: str
) -> dict[uuid.UUID, int]:
    """Unread (other-side) message counts for many tickets in one grouped query.

    Avoids the N+1 of calling ``count_unread`` per row in a list view. Tickets
    with no unread messages are simply absent from the returned mapping.
    """
    if not ticket_ids:
        return {}
    statement = (
        select(SupportMessage.ticket_id, func.count())
        .where(
            SupportMessage.ticket_id.in_(ticket_ids),
            SupportMessage.sender_role != reader_role,
            SupportMessage.read_at.is_(None),
        )
        .group_by(SupportMessage.ticket_id)
    )
    counts: dict[uuid.UUID, int] = {}
    for ticket_id, count in (await session.execute(statement)).all():
        counts[ticket_id] = count
    return counts
