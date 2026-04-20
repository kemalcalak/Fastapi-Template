import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import send_email
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.security import create_password_reset_token
from app.models.user import User
from app.repositories.admin.user import (
    is_last_active_admin,
    list_users_admin,
)
from app.repositories.user import (
    delete_user,
    get_user_by_id,
    suspend_user,
    unsuspend_user,
    update_user,
)
from app.schemas.admin import (
    AdminUserDetail,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserUpdate,
)
from app.schemas.msg import Message
from app.schemas.user import Language, SystemRole
from app.schemas.user_activity import ActivityType, ResourceType
from app.use_cases.log_activity import log_activity
from app.utils.email_templates import generate_password_reset_email


async def list_users_admin_service(
    session: AsyncSession,
    *,
    skip: int,
    limit: int,
    search: str | None,
    role: SystemRole | None,
    is_active: bool | None,
    is_verified: bool | None,
) -> AdminUserListResponse:
    """Return the filtered, paginated admin user list."""
    users, total = await list_users_admin(
        session,
        skip=skip,
        limit=limit,
        search=search,
        role=role,
        is_active=is_active,
        is_verified=is_verified,
    )
    return AdminUserListResponse(
        data=[AdminUserListItem.model_validate(u) for u in users],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_user_admin_service(
    session: AsyncSession, user_id: uuid.UUID
) -> AdminUserDetail:
    """Return a single user's full admin view or raise 404."""
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    return AdminUserDetail.model_validate(user)


async def _load_target(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Fetch a target user for admin mutation or raise 404."""
    target = await get_user_by_id(session, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    return target


def _guard_not_self(admin_id: uuid.UUID, target_id: uuid.UUID, message: str) -> None:
    """Raise 400 when an admin targets their own account for a protected action."""
    if admin_id == target_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )


async def update_user_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
) -> AdminUserDetail:
    """Apply an admin-authored update to a user, honouring last-admin guards."""
    target = await _load_target(session, user_id)

    update_data = payload.model_dump(exclude_unset=True)

    new_role = update_data.get("role")
    if new_role is not None and new_role != target.role:
        _guard_not_self(
            current_user.id, target.id, ErrorMessages.ADMIN_CANNOT_MODIFY_SELF
        )
        demoting_admin = (
            target.role == SystemRole.ADMIN.value and new_role != SystemRole.ADMIN
        )
        if demoting_admin and await is_last_active_admin(session, target.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorMessages.ADMIN_CANNOT_DEMOTE_LAST_ADMIN,
            )
        update_data["role"] = new_role.value

    if "is_active" in update_data and update_data["is_active"] != target.is_active:
        _guard_not_self(
            current_user.id, target.id, ErrorMessages.ADMIN_CANNOT_MODIFY_SELF
        )
        deactivating_admin = (
            target.role == SystemRole.ADMIN.value and update_data["is_active"] is False
        )
        if deactivating_admin and await is_last_active_admin(session, target.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorMessages.ADMIN_CANNOT_DEMOTE_LAST_ADMIN,
            )

    updated = await update_user(session, target, update_data)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=updated.id,
        details={"updated_fields": list(update_data.keys()), "by_admin": True},
        request=request,
    )

    return AdminUserDetail.model_validate(updated)


async def suspend_user_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
) -> Message:
    """Permanently suspend a user.

    The suspended account cannot log in and cannot self-reactivate. It is never
    auto-deleted — only an admin may lift the suspension via unsuspend.
    """
    target = await _load_target(session, user_id)
    _guard_not_self(current_user.id, target.id, ErrorMessages.ADMIN_CANNOT_MODIFY_SELF)

    if target.role == SystemRole.ADMIN.value and await is_last_active_admin(
        session, target.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.ADMIN_CANNOT_DEMOTE_LAST_ADMIN,
        )

    if target.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.ACCOUNT_ALREADY_SUSPENDED,
        )

    await suspend_user(session, target)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={"action": "admin_suspended_user"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.ADMIN_USER_SUSPENDED)


async def unsuspend_user_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
) -> Message:
    """Lift an existing admin suspension and re-enable the account."""
    target = await _load_target(session, user_id)

    if target.suspended_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.ACCOUNT_NOT_SUSPENDED,
        )

    await unsuspend_user(session, target)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={"action": "admin_unsuspended_user"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.ADMIN_USER_UNSUSPENDED)


async def delete_user_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
) -> Message:
    """Hard-delete a user. Protects the admin's own account and the last admin."""
    target = await _load_target(session, user_id)
    _guard_not_self(current_user.id, target.id, ErrorMessages.ADMIN_CANNOT_DELETE_SELF)

    if target.role == SystemRole.ADMIN.value and await is_last_active_admin(
        session, target.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.ADMIN_CANNOT_DELETE_LAST_ADMIN,
        )

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.DELETE,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        details={"action": "admin_deleted_user", "email": target.email},
        request=request,
    )

    await delete_user(session, target)

    return Message(success=True, message=SuccessMessages.ADMIN_USER_DELETED)


async def reset_password_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
    lang: Language = Language.EN,
) -> Message:
    """Trigger a password-reset email on behalf of the target user.

    The admin never sees or sets the new password; the user completes the reset
    via the standard email-link flow used by self-service password recovery.
    """
    target = await _load_target(session, user_id)

    token = create_password_reset_token(target.email)
    reset_url = f"{settings.FRONTEND_HOST}/reset-password?token={token}"

    email_data = generate_password_reset_email(
        reset_link=reset_url,
        project_name=settings.PROJECT_NAME,
        lang=lang,
    )
    await send_email(
        to=target.email,
        subject=email_data["subject"],
        body=email_data["html"],
        plain_text=email_data["plain_text"],
        user_id=str(target.id),
        is_html=True,
    )

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        resource_id=target.id,
        details={"action": "admin_triggered_password_reset"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.ADMIN_PASSWORD_RESET_SENT)
