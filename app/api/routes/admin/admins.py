import uuid

from fastapi import APIRouter, Request, status

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentSuperAdmin, SessionDep
from app.schemas.admin import (
    AdminListResponse,
    AdminMutationResponse,
    AdminPermissionsUpdate,
    AdminPromote,
    PermissionCatalogResponse,
)
from app.schemas.msg import Message
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.admin_service import (
    demote_admin_service,
    get_permission_catalog_service,
    list_admins_service,
    promote_to_admin_service,
    update_admin_permissions_service,
)

router = APIRouter()


@router.get("", response_model=AdminListResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins",
)
async def list_admins_endpoint(
    _request: Request,
    _admin: CurrentSuperAdmin,
    session: SessionDep,
) -> AdminListResponse:
    """List every admin-tier account with its permissions (superadmin only)."""
    return await list_admins_service(session=session)


@router.get("/permissions", response_model=PermissionCatalogResponse)
async def list_permission_catalog(
    _admin: CurrentSuperAdmin,
) -> PermissionCatalogResponse:
    """Return all assignable permission keys for the grant UI (superadmin only)."""
    return get_permission_catalog_service()


@router.post(
    "",
    response_model=AdminMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins",
)
async def promote_admin(
    request: Request,
    current_user: CurrentSuperAdmin,
    session: SessionDep,
    payload: AdminPromote,
) -> AdminMutationResponse:
    """Promote a user to admin with an initial permission set (superadmin only)."""
    return await promote_to_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        payload=payload,
    )


@router.patch("/{user_id}/permissions", response_model=AdminMutationResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins/{user_id}/permissions",
)
async def set_admin_permissions(
    request: Request,
    current_user: CurrentSuperAdmin,
    session: SessionDep,
    user_id: uuid.UUID,
    payload: AdminPermissionsUpdate,
) -> AdminMutationResponse:
    """Replace an admin's permission grants with the supplied set (superadmin only)."""
    return await update_admin_permissions_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
        payload=payload,
    )


@router.delete("/{user_id}", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins/{user_id}",
)
async def demote_admin(
    request: Request,
    current_user: CurrentSuperAdmin,
    session: SessionDep,
    user_id: uuid.UUID,
) -> Message:
    """Demote an admin back to a regular user, revoking every grant (superadmin only)."""
    return await demote_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )
