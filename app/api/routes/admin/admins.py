import uuid

from fastapi import APIRouter, Request, status

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentSuperAdmin, SessionDep
from app.schemas.admin import (
    AdminCreate,
    AdminListResponse,
    AdminMutationResponse,
    AdminPermissionsUpdate,
    PermissionCatalogResponse,
)
from app.schemas.msg import Message
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.admin_service import (
    create_admin_service,
    delete_admin_service,
    demote_superadmin_service,
    get_permission_catalog_service,
    list_admins_service,
    promote_admin_to_superadmin_service,
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
    activity_type=ActivityType.CREATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins",
)
async def create_admin(
    request: Request,
    current_user: CurrentSuperAdmin,
    session: SessionDep,
    payload: AdminCreate,
) -> AdminMutationResponse:
    """Create a new admin account with an initial permission set (superadmin only)."""
    return await create_admin_service(
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


@router.post("/{user_id}/promote", response_model=AdminMutationResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins/{user_id}/promote",
)
async def promote_admin(
    request: Request,
    current_user: CurrentSuperAdmin,
    session: SessionDep,
    user_id: uuid.UUID,
) -> AdminMutationResponse:
    """Promote an admin to superadmin (root superadmin only)."""
    return await promote_admin_to_superadmin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )


@router.post("/{user_id}/demote", response_model=AdminMutationResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins/{user_id}/demote",
)
async def demote_superadmin(
    request: Request,
    current_user: CurrentSuperAdmin,
    session: SessionDep,
    user_id: uuid.UUID,
) -> AdminMutationResponse:
    """Demote a superadmin back to admin (root superadmin only)."""
    return await demote_superadmin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )


@router.delete("/{user_id}", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.DELETE,
    resource_type=ResourceType.USER,
    endpoint="/admin/admins/{user_id}",
)
async def delete_admin(
    request: Request,
    current_user: CurrentSuperAdmin,
    session: SessionDep,
    user_id: uuid.UUID,
) -> Message:
    """Hard-delete an admin account (superadmin only)."""
    return await delete_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )
