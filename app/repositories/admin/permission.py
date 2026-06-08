import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_permission import AdminPermission
from app.schemas.admin_permission import Permission

# Valid keys snapshot so a grant left over from a removed enum member is skipped
# rather than raising when materialised back into ``Permission``.
_VALID_PERMISSIONS = {perm.value for perm in Permission}


async def get_user_permissions(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Permission]:
    """Return the permission keys granted to a single admin."""
    stmt = select(AdminPermission.permission).where(AdminPermission.user_id == user_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [Permission(value) for value in rows if value in _VALID_PERMISSIONS]


async def has_permission(
    session: AsyncSession, user_id: uuid.UUID, permission: Permission
) -> bool:
    """Return True if the admin holds the given permission grant."""
    stmt = (
        select(AdminPermission.id)
        .where(
            AdminPermission.user_id == user_id,
            AdminPermission.permission == permission.value,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).first() is not None
