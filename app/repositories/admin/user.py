import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.user import User
from app.schemas.user import SystemRole
from app.utils.db_search import LIKE_ESCAPE_CHAR, ilike_contains


def _filtered_users_stmt(
    *,
    search: str | None,
    role: SystemRole | None,
    is_active: bool | None,
    is_verified: bool | None,
) -> Select:
    """Build the filtered base statement shared by count and list queries."""
    stmt = select(User)
    if search:
        # ``ILIKE`` on the raw columns so the ``pg_trgm`` GIN indexes on
        # email/first_name/last_name can actually serve the query. Wrapping
        # with ``func.lower(...)`` would defeat the index.
        like = ilike_contains(search)
        stmt = stmt.where(
            or_(
                User.email.ilike(like, escape=LIKE_ESCAPE_CHAR),
                User.first_name.ilike(like, escape=LIKE_ESCAPE_CHAR),
                User.last_name.ilike(like, escape=LIKE_ESCAPE_CHAR),
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
    base_stmt = _filtered_users_stmt(
        search=search, role=role, is_active=is_active, is_verified=is_verified
    )

    count_stmt = base_stmt.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = (await session.execute(count_stmt)).scalar_one()

    rows_stmt = base_stmt.order_by(User.created_at.desc()).offset(skip).limit(limit)
    users = (await session.execute(rows_stmt)).scalars().all()

    return users, total


async def list_admins(session: AsyncSession) -> Sequence[User]:
    """Return all admin and superadmin accounts, newest first."""
    stmt = (
        select(User)
        .where(User.role.in_([SystemRole.ADMIN.value, SystemRole.SUPERADMIN.value]))
        .order_by(User.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def superadmin_exists(session: AsyncSession) -> bool:
    """Return True if at least one superadmin account exists."""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.role == SystemRole.SUPERADMIN.value)
    )
    return (await session.execute(stmt)).scalar_one() > 0


async def root_superadmin_exists(session: AsyncSession) -> bool:
    """Return True if a designated root superadmin already exists."""
    stmt = (
        select(func.count()).select_from(User).where(User.is_root_superadmin.is_(True))
    )
    return (await session.execute(stmt)).scalar_one() > 0


async def transfer_root_superadmin(
    session: AsyncSession,
    *,
    new_root_id: uuid.UUID,
    old_root_id: uuid.UUID,
) -> User:
    """Atomically move the root flag from the old root to the new one.

    Both updates ride a single transaction/commit so a failure can never leave
    two root superadmins (the flag has no DB-level uniqueness). Returns the
    freshly-loaded new root for the response payload.
    """
    await session.execute(
        update(User).where(User.id == new_root_id).values(is_root_superadmin=True)
    )
    await session.execute(
        update(User).where(User.id == old_root_id).values(is_root_superadmin=False)
    )
    await session.commit()
    result = await session.execute(select(User).where(User.id == new_root_id))
    return result.scalars().one()


async def get_earliest_superadmin(session: AsyncSession) -> User | None:
    """Return the oldest superadmin account (earliest ``created_at``), if any."""
    stmt = (
        select(User)
        .where(User.role == SystemRole.SUPERADMIN.value)
        .order_by(User.created_at.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


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


async def is_last_active_superadmin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return True if ``user_id`` is the only remaining active superadmin."""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(
            User.role == SystemRole.SUPERADMIN.value,
            User.is_active.is_(True),
            User.id != user_id,
        )
    )
    other_superadmins = (await session.execute(stmt)).scalar_one()
    return other_superadmins == 0
