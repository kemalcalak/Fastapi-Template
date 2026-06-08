import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from app.models.support import SupportTicket
from app.models.user import User


def _filtered_tickets_stmt(
    *,
    search: str | None,
    status: str | None,
    priority: str | None,
    assigned_admin_id: uuid.UUID | None,
) -> Select:
    """Build the filtered base statement shared by count and list queries.

    Search matches the ticket subject or the owner's email/name; the owner is
    reached via an explicit join on ``SupportTicket.user_id``.
    """
    stmt = select(SupportTicket)
    if search:
        like = f"%{search}%"
        stmt = stmt.join(User, SupportTicket.user_id == User.id).where(
            or_(
                SupportTicket.subject.ilike(like),
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            )
        )
    if status is not None:
        stmt = stmt.where(SupportTicket.status == status)
    if priority is not None:
        stmt = stmt.where(SupportTicket.priority == priority)
    if assigned_admin_id is not None:
        stmt = stmt.where(SupportTicket.assigned_admin_id == assigned_admin_id)
    return stmt


async def list_tickets_admin(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_admin_id: uuid.UUID | None = None,
) -> tuple[Sequence[SupportTicket], int]:
    """Return a filtered, paginated admin ticket page plus the total count."""
    base_stmt = _filtered_tickets_stmt(
        search=search,
        status=status,
        priority=priority,
        assigned_admin_id=assigned_admin_id,
    )

    count_stmt = base_stmt.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = (await session.execute(count_stmt)).scalar_one()

    list_stmt = (
        base_stmt.options(
            selectinload(SupportTicket.user),
            selectinload(SupportTicket.assigned_admin),
        )
        .order_by(SupportTicket.last_message_at.desc())
        .offset(skip)
        .limit(limit)
    )
    tickets = (await session.execute(list_stmt)).scalars().all()
    return tickets, total
