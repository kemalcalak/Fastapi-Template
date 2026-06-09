import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
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


async def get_permissions_for_users(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[Permission]]:
    """Return a ``user_id -> granted permissions`` map for the given users.

    Fetches every grant in one query to avoid an N+1 over the admin list.
    """
    if not user_ids:
        return {}
    stmt = select(AdminPermission.user_id, AdminPermission.permission).where(
        AdminPermission.user_id.in_(list(user_ids))
    )
    rows = (await session.execute(stmt)).all()
    result: dict[uuid.UUID, list[Permission]] = {}
    for user_id, permission in rows:
        if permission in _VALID_PERMISSIONS:
            result.setdefault(user_id, []).append(Permission(permission))
    return result


async def set_user_permissions(
    session: AsyncSession,
    user_id: uuid.UUID,
    permissions: list[Permission],
    granted_by: uuid.UUID,
) -> None:
    """Replace a user's permission grants with exactly ``permissions``.

    Existing rows are cleared first so the call is idempotent and also serves as
    a full revoke when ``permissions`` is empty (e.g. on demotion). Duplicates
    are dropped to respect the ``(user_id, permission)`` unique constraint.
    """
    await session.execute(
        delete(AdminPermission).where(AdminPermission.user_id == user_id)
    )
    for permission in dict.fromkeys(permissions):
        session.add(
            AdminPermission(
                user_id=user_id,
                permission=permission.value,
                granted_by=granted_by,
            )
        )
    await session.commit()
