import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentSuperUser, SessionDep
from app.core.messages.success_message import SuccessMessages
from app.schemas.admin import (
    AdminUserDetail,
    AdminUserListResponse,
    AdminUserUpdate,
    AdminUserUpdateResponse,
)
from app.schemas.msg import Message
from app.schemas.user import Language, SystemRole
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.user_service import (
    activate_user_admin_service,
    deactivate_user_admin_service,
    delete_user_admin_service,
    get_user_admin_service,
    list_users_admin_service,
    reset_password_admin_service,
    update_user_admin_service,
)

router = APIRouter()


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    _admin: CurrentSuperUser,
    session: SessionDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    search: Annotated[str | None, Query(max_length=255)] = None,
    role: SystemRole | None = None,
    is_active: bool | None = None,
    is_verified: bool | None = None,
) -> AdminUserListResponse:
    """List users with admin-only filters, search, and pagination."""
    return await list_users_admin_service(
        session=session,
        skip=skip,
        limit=limit,
        search=search,
        role=role,
        is_active=is_active,
        is_verified=is_verified,
    )


@router.get("/{user_id}", response_model=AdminUserDetail)
async def get_user(
    _admin: CurrentSuperUser,
    session: SessionDep,
    user_id: uuid.UUID,
) -> AdminUserDetail:
    """Return the full admin view of a single user."""
    return await get_user_admin_service(session=session, user_id=user_id)


@router.patch("/{user_id}", response_model=AdminUserUpdateResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}",
)
async def update_user(
    request: Request,
    current_user: CurrentSuperUser,
    session: SessionDep,
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
) -> AdminUserUpdateResponse:
    """Admin-authored update of a user's profile, role, or status."""
    user = await update_user_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
        payload=payload,
    )
    return AdminUserUpdateResponse(
        user=user, message=SuccessMessages.ADMIN_USER_UPDATED
    )


@router.post("/{user_id}/activate", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}/activate",
)
async def activate_user(
    request: Request,
    current_user: CurrentSuperUser,
    session: SessionDep,
    user_id: uuid.UUID,
) -> Message:
    """Reactivate a deactivated user and cancel any scheduled deletion."""
    return await activate_user_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )


@router.post("/{user_id}/deactivate", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}/deactivate",
)
async def deactivate_user(
    request: Request,
    current_user: CurrentSuperUser,
    session: SessionDep,
    user_id: uuid.UUID,
) -> Message:
    """Deactivate a user and start the configured deletion grace window."""
    return await deactivate_user_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )


@router.delete("/{user_id}", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.DELETE,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}",
)
async def delete_user(
    request: Request,
    current_user: CurrentSuperUser,
    session: SessionDep,
    user_id: uuid.UUID,
) -> Message:
    """Hard-delete a user. Guards self-delete and last-admin removal."""
    return await delete_user_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )


@router.post("/{user_id}/reset-password", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.AUTH,
    endpoint="/admin/users/{user_id}/reset-password",
)
async def reset_user_password(
    request: Request,
    current_user: CurrentSuperUser,
    session: SessionDep,
    user_id: uuid.UUID,
    lang: Language = Language.EN,
) -> Message:
    """Send a password-reset email to the target user.

    The admin never sees or sets the password — the user completes the reset
    via the standard email-link flow.
    """
    return await reset_password_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
        lang=lang,
    )
