import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import SystemRole


def _apply_filters(
    stmt: Select,
    *,
    search: str | None,
    role: SystemRole | None,
    is_active: bool | None,
    is_verified: bool | None,
) -> Select:
    """Attach admin-listing filters to a base statement."""
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
            )
        )
    if role is not None:
        stmt = stmt.where(User.role == role.value)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if is_verified is not None:
        stmt = stmt.where(User.is_verified == is_verified)
    return stmt


async def list_users_admin(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    role: SystemRole | None = None,
    is_active: bool | None = None,
    is_verified: bool | None = None,
) -> tuple[Sequence[User], int]:
    """Return a filtered, paginated user page plus the matching total count."""
    count_stmt = _apply_filters(
        select(func.count()).select_from(User),
        search=search,
        role=role,
        is_active=is_active,
        is_verified=is_verified,
    )
    total = (await session.execute(count_stmt)).scalar_one()

    rows_stmt = _apply_filters(
        select(User),
        search=search,
        role=role,
        is_active=is_active,
        is_verified=is_verified,
    )
    rows_stmt = rows_stmt.order_by(User.created_at.desc()).offset(skip).limit(limit)
    users = (await session.execute(rows_stmt)).scalars().all()

    return users, total


async def count_active_admins(session: AsyncSession) -> int:
    """Count admin users who are still active (used by last-admin guard)."""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.role == SystemRole.ADMIN.value, User.is_active.is_(True))
    )
    return (await session.execute(stmt)).scalar_one()


async def is_last_active_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return True if ``user_id`` is the only remaining active admin."""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(
            User.role == SystemRole.ADMIN.value,
            User.is_active.is_(True),
            User.id != user_id,
        )
    )
    other_admins = (await session.execute(stmt)).scalar_one()
    return other_admins == 0
