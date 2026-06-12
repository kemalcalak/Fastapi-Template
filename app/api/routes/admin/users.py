import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.decorators import audit_unexpected_failure
from app.api.deps import SessionDep, require_permission
from app.core.messages.success_message import SuccessMessages
from app.core.rate_limit import rate_limit_strict
from app.models.user import User
from app.schemas.admin import (
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserUpdate,
    AdminUserUpdateResponse,
)
from app.schemas.admin_permission import Permission
from app.schemas.msg import Message
from app.schemas.user import Language, SystemRole
from app.schemas.user_activity import ActivityType, ResourceType
from app.schemas.user_session import SessionListResponse, SessionsRevokedResponse
from app.services.admin.session_service import (
    list_user_sessions_admin_service,
    revoke_user_sessions_admin_service,
)
from app.services.admin.user_service import (
    change_password_admin_service,
    delete_user_admin_service,
    get_user_admin_service,
    list_users_admin_service,
    suspend_user_admin_service,
    unsuspend_user_admin_service,
    update_user_admin_service,
)

router = APIRouter()

AdminUsersRead = Annotated[User, Depends(require_permission(Permission.USERS_READ))]
AdminUsersSuspend = Annotated[
    User, Depends(require_permission(Permission.USERS_SUSPEND))
]
AdminUsersDelete = Annotated[User, Depends(require_permission(Permission.USERS_DELETE))]
AdminUsersPasswordReset = Annotated[
    User, Depends(require_permission(Permission.USERS_PASSWORD_RESET))
]
AdminUsersSessions = Annotated[
    User, Depends(require_permission(Permission.USERS_SESSIONS))
]


AdminUserUpdateAuth = Annotated[
    User,
    Depends(require_permission(Permission.USERS_WRITE)),
]


@router.get("", response_model=AdminUserListResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.USER,
    endpoint="/admin/users",
)
async def list_users(
    _request: Request,
    _admin: AdminUsersRead,
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


@router.get("/{user_id}", response_model=AdminUserListItem)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}",
)
async def get_user(
    _request: Request,
    _admin: AdminUsersRead,
    session: SessionDep,
    user_id: uuid.UUID,
) -> AdminUserListItem:
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
    current_user: AdminUserUpdateAuth,
    session: SessionDep,
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
) -> AdminUserUpdateResponse:
    """Admin-authored update of a user's profile or status."""
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


@router.post("/{user_id}/suspend", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}/suspend",
)
async def suspend_user(
    request: Request,
    current_user: AdminUsersSuspend,
    session: SessionDep,
    user_id: uuid.UUID,
) -> Message:
    """Permanently suspend a user. Only an admin can later unsuspend them."""
    return await suspend_user_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
    )


@router.post("/{user_id}/unsuspend", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}/unsuspend",
)
async def unsuspend_user(
    request: Request,
    current_user: AdminUsersSuspend,
    session: SessionDep,
    user_id: uuid.UUID,
) -> Message:
    """Lift an existing admin suspension and re-enable the account."""
    return await unsuspend_user_admin_service(
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
    current_user: AdminUsersDelete,
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


@router.get("/{user_id}/sessions", response_model=SessionListResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}/sessions",
)
async def list_user_sessions(
    _request: Request,
    _admin: AdminUsersSessions,
    session: SessionDep,
    user_id: uuid.UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SessionListResponse:
    """List a user's active sessions for the admin detail view."""
    return await list_user_sessions_admin_service(
        session, user_id=user_id, skip=skip, limit=limit
    )


@router.delete("/{user_id}/sessions", response_model=SessionsRevokedResponse)
@rate_limit_strict("10/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/admin/users/{user_id}/sessions",
)
async def revoke_user_sessions(
    request: Request,
    current_user: AdminUsersSessions,
    session: SessionDep,
    user_id: uuid.UUID,
) -> SessionsRevokedResponse:
    """Terminate every session of a user — remote logout on all their devices."""
    return await revoke_user_sessions_admin_service(
        request,
        session,
        current_user=current_user,
        user_id=user_id,
    )


@router.post("/{user_id}/change-password", response_model=Message)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.AUTH,
    endpoint="/admin/users/{user_id}/change-password",
)
async def change_user_password(
    request: Request,
    current_user: AdminUsersPasswordReset,
    session: SessionDep,
    user_id: uuid.UUID,
    lang: Language = Language.EN,
) -> Message:
    """Force-rotate the target user's password to an unknown random value.

    The new password is never returned. The target user receives a neutral
    notification email and must regain access via the standard 'Forgot
    Password' flow on the login page.
    """
    return await change_password_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=user_id,
        lang=lang,
    )
