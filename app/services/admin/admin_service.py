import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.realtime import account_topic, publish_safe
from app.core.security import aget_password_hash
from app.models.user import User
from app.repositories.admin.permission import (
    get_permissions_for_users,
    set_user_permissions,
)
from app.repositories.admin.user import list_admins
from app.repositories.user import (
    create_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    update_user,
)
from app.schemas.account import AccountEvent, AccountEventType
from app.schemas.admin import (
    AdminCreate,
    AdminListItem,
    AdminListResponse,
    AdminMutationResponse,
    AdminPermissionsUpdate,
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
        is_root_superadmin=user.is_root_superadmin,
        permissions=permissions,
    )


def _effective_permissions(user: User, granted: list[Permission]) -> list[Permission]:
    """Superadmins implicitly hold every permission; admins hold their grants."""
    if user.role == SystemRole.SUPERADMIN.value:
        return list(Permission)
    return granted


async def _notify_permissions_changed(user_id: uuid.UUID) -> None:
    """Push a best-effort ``permissions_updated`` event to the user's socket.

    The browser uses this as a signal to refetch ``/users/me`` so a permission
    grant or revoke takes effect immediately without a re-login.
    """
    await publish_safe(
        account_topic(user_id),
        AccountEvent(type=AccountEventType.PERMISSIONS_UPDATED),
    )


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


async def create_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    payload: AdminCreate,
) -> AdminMutationResponse:
    """Create a brand-new admin account with an initial permission set.

    Superadmins provision admins directly (rather than promoting an existing
    user), so the account is created already active and verified. The supplied
    password lets the new admin sign in immediately.
    """
    existing = await get_user_by_email(session, payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorMessages.EMAIL_ALREADY_EXISTS,
        )

    hashed_password = await aget_password_hash(payload.password)
    admin = User(
        email=payload.email,
        hashed_password=hashed_password,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=SystemRole.ADMIN.value,
        is_active=True,
        is_verified=True,
    )
    await create_user(session, admin)

    permissions = list(dict.fromkeys(payload.permissions))
    await set_user_permissions(session, admin.id, permissions, current_user.id)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.CREATE,
        resource_type=ResourceType.USER,
        resource_id=admin.id,
        details={
            "action": "created_admin",
            "email": admin.email,
            "permissions": [permission.value for permission in permissions],
        },
        request=request,
    )

    return AdminMutationResponse(
        admin=_to_list_item(admin, permissions),
        message=SuccessMessages.ADMIN_CREATED,
    )


async def promote_admin_to_superadmin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
) -> AdminMutationResponse:
    """Promote a plain admin to superadmin. Only the root superadmin may do this.

    The superadmin tier (promote/demote) is governed exclusively by the root
    superadmin. Existing per-action grants are cleared because superadmins hold
    every permission implicitly.
    """
    if not current_user.is_root_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.ONLY_ROOT_SUPERADMIN,
        )

    target = await get_user_by_id(session, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    if target.role != SystemRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.NOT_AN_ADMIN,
        )

    await set_user_permissions(session, target.id, [], current_user.id)
    await update_user(session, target, {"role": SystemRole.SUPERADMIN.value})

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={"action": "promoted_to_superadmin"},
        request=request,
    )
    await _notify_permissions_changed(target.id)

    return AdminMutationResponse(
        admin=_to_list_item(target, _effective_permissions(target, [])),
        message=SuccessMessages.SUPERADMIN_PROMOTED,
    )


async def demote_superadmin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
) -> AdminMutationResponse:
    """Demote a superadmin back to a plain admin. Only the root may do this.

    The root superadmin's own role is immutable here (use the email-verified
    root transfer to hand over root). The demoted account becomes a grant-less
    admin until permissions are assigned.
    """
    if not current_user.is_root_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.ONLY_ROOT_SUPERADMIN,
        )

    target = await get_user_by_id(session, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.SUPERADMIN_ROLE_IMMUTABLE,
        )
    if target.role != SystemRole.SUPERADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.NOT_A_SUPERADMIN,
        )

    await update_user(session, target, {"role": SystemRole.ADMIN.value})
    await set_user_permissions(session, target.id, [], current_user.id)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={"action": "demoted_superadmin_to_admin"},
        request=request,
    )
    await _notify_permissions_changed(target.id)

    return AdminMutationResponse(
        admin=_to_list_item(target, []),
        message=SuccessMessages.SUPERADMIN_DEMOTED,
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
    await _notify_permissions_changed(target.id)

    return AdminMutationResponse(
        admin=_to_list_item(target, permissions),
        message=SuccessMessages.ADMIN_PERMISSIONS_UPDATED,
    )


async def delete_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
) -> Message:
    """Hard-delete an admin account (grants cascade at the DB level).

    Removing admin access is a deletion, not a demotion: there is no longer an
    admin→user downgrade path. Superadmins are never deleted here — they must be
    demoted to admin first (root only), which keeps the superadmin tier guarded.
    """
    target = await get_user_by_id(session, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    if target.role != SystemRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.NOT_AN_ADMIN,
        )

    target_id = target.id
    target_email = target.email
    await delete_user(session, target)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.DELETE,
        resource_type=ResourceType.USER,
        resource_id=target_id,
        details={"action": "deleted_admin", "email": target_email},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.ADMIN_ACCOUNT_DELETED)
