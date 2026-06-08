import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.user import User
from app.repositories.admin.permission import (
    get_permissions_for_users,
    set_user_permissions,
)
from app.repositories.admin.user import list_admins
from app.repositories.user import get_user_by_id, update_user
from app.schemas.admin import (
    AdminListItem,
    AdminListResponse,
    AdminMutationResponse,
    AdminPermissionsUpdate,
    AdminPromote,
    PermissionCatalogResponse,
)
from app.schemas.admin_permission import Permission
from app.schemas.msg import Message
from app.schemas.user import SystemRole
from app.schemas.user_activity import ActivityType, ResourceType
from app.use_cases.log_activity import log_activity


def _to_list_item(user: User, permissions: list[Permission]) -> AdminListItem:
    """Build an admin row from a user and its already-resolved permissions."""
    return AdminListItem(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active,
        permissions=permissions,
    )


def _effective_permissions(user: User, granted: list[Permission]) -> list[Permission]:
    """Superadmins implicitly hold every permission; admins hold their grants."""
    if user.role == SystemRole.SUPERADMIN.value:
        return list(Permission)
    return granted


def get_permission_catalog_service() -> PermissionCatalogResponse:
    """Return every assignable RBAC permission key for the grant UI."""
    return PermissionCatalogResponse(permissions=list(Permission))


async def list_admins_service(session: AsyncSession) -> AdminListResponse:
    """List every admin-tier account with the permissions it holds."""
    admins = await list_admins(session)
    permissions_map = await get_permissions_for_users(
        session, [admin.id for admin in admins]
    )
    data = [
        _to_list_item(
            admin, _effective_permissions(admin, permissions_map.get(admin.id, []))
        )
        for admin in admins
    ]
    return AdminListResponse(data=data, total=len(data))


async def promote_to_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    payload: AdminPromote,
) -> AdminMutationResponse:
    """Promote a plain user to admin and seed their initial permission grants."""
    target = await get_user_by_id(session, payload.user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    if target.role != SystemRole.USER.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorMessages.ALREADY_AN_ADMIN,
        )

    await update_user(session, target, {"role": SystemRole.ADMIN.value})
    await set_user_permissions(session, target.id, payload.permissions, current_user.id)
    permissions = list(dict.fromkeys(payload.permissions))

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={
            "action": "promoted_to_admin",
            "permissions": [permission.value for permission in permissions],
        },
        request=request,
    )

    return AdminMutationResponse(
        admin=_to_list_item(target, permissions),
        message=SuccessMessages.ADMIN_PROMOTED,
    )


async def update_admin_permissions_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
    payload: AdminPermissionsUpdate,
) -> AdminMutationResponse:
    """Replace a plain admin's permission grants with the supplied set."""
    target = await get_user_by_id(session, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    if target.role == SystemRole.SUPERADMIN.value:
        # Superadmins hold every permission implicitly — nothing to grant.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.ADMIN_CANNOT_MODIFY_SUPERADMIN,
        )
    if target.role != SystemRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.NOT_AN_ADMIN,
        )

    await set_user_permissions(session, target.id, payload.permissions, current_user.id)
    permissions = list(dict.fromkeys(payload.permissions))

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={
            "action": "set_admin_permissions",
            "permissions": [permission.value for permission in permissions],
        },
        request=request,
    )

    return AdminMutationResponse(
        admin=_to_list_item(target, permissions),
        message=SuccessMessages.ADMIN_PERMISSIONS_UPDATED,
    )


async def demote_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
) -> Message:
    """Demote a plain admin back to a regular user, revoking every grant."""
    target = await get_user_by_id(session, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    if target.role == SystemRole.SUPERADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.SUPERADMIN_ROLE_IMMUTABLE,
        )
    if target.role != SystemRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.NOT_AN_ADMIN,
        )

    await set_user_permissions(session, target.id, [], current_user.id)
    await update_user(session, target, {"role": SystemRole.USER.value})

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={"action": "demoted_to_user"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.ADMIN_DEMOTED)
