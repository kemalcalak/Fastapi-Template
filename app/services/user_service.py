import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import check_mx_record, is_disposable_email, send_email
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.repositories.token_blacklist import add_token_to_blacklist
from app.repositories.user import (
    create_user,
    deactivate_user,
    get_user_by_email,
    get_user_by_id,
    get_users_with_count,
    reactivate_user,
    update_user,
)
from app.schemas.msg import Message
from app.schemas.user import (
    Language,
    UserCreate,
    UserPublic,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType
from app.services.user_activity_service import log_activity
from app.utils.email_templates import generate_account_deactivation_email


async def deactivate_own_account_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    password: str,
    lang: Language = Language.EN,
) -> Message:
    """Deactivate the current user's account and schedule deletion.

    Verifies the password, starts the grace window configured by
    ``ACCOUNT_DELETION_GRACE_DAYS``, blacklists the caller's active JWTs so
    the session cannot be resumed, and logs an audit entry.
    """
    if current_user.deletion_scheduled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.ACCOUNT_ALREADY_DEACTIVATED,
        )

    if not verify_password(password, current_user.hashed_password):
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.DELETE,
            resource_type=ResourceType.USER,
            status=ActivityStatus.FAILURE,
            details={"reason": "invalid_password"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_PASSWORD,
        )

    await deactivate_user(
        session, current_user, grace_days=settings.ACCOUNT_DELETION_GRACE_DAYS
    )

    # Invalidate the caller's active tokens so the session can't be replayed.
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")
    if access_token:
        await add_token_to_blacklist(access_token)
    if refresh_token:
        await add_token_to_blacklist(refresh_token)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=current_user.id,
        details={
            "action": "account_deactivated",
            "grace_days": settings.ACCOUNT_DELETION_GRACE_DAYS,
        },
        request=request,
    )

    reactivate_link = f"{settings.FRONTEND_HOST}/{lang}/account-deactivated"
    email_data = generate_account_deactivation_email(
        reactivate_link=reactivate_link,
        grace_days=settings.ACCOUNT_DELETION_GRACE_DAYS,
        project_name=settings.PROJECT_NAME,
        lang=lang,
    )
    await send_email(
        to=current_user.email,
        subject=email_data["subject"],
        body=email_data["html"],
        plain_text=email_data["plain_text"],
        user_id=str(current_user.id),
    )

    return Message(success=True, message=SuccessMessages.ACCOUNT_DEACTIVATED)


async def reactivate_own_account_service(
    request: Request, session: AsyncSession, current_user: User
) -> Message:
    """Cancel a pending deletion and re-enable the account."""
    if current_user.deletion_scheduled_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.ACCOUNT_NOT_DEACTIVATED,
        )

    await reactivate_user(session, current_user)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=current_user.id,
        details={"action": "account_reactivated"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.ACCOUNT_REACTIVATED)


async def create_user_service(
    request: Request | None,
    session: AsyncSession,
    user_create: UserCreate,
    current_user: User | None = None,
) -> User:
    """
    Business logic to create a new user.
    Checks for email availability and hashes the password.
    """
    # 1. Reject disposable / unreachable email domains (same checks the
    # reset/verify flows use so attackers can't register with throwaway mail).
    if await is_disposable_email(user_create.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.DISPOSABLE_EMAIL_NOT_ALLOWED,
        )
    if not await check_mx_record(user_create.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.INVALID_EMAIL_DOMAIN,
        )

    # 2. Guard check: Email must be unique
    existing_user = await get_user_by_email(session, email=user_create.email)
    if existing_user:
        if current_user and request:
            await log_activity(
                session=session,
                user_id=current_user.id,
                activity_type=ActivityType.CREATE,
                resource_type=ResourceType.USER,
                status=ActivityStatus.FAILURE,
                details={"reason": "email_already_exists", "email": user_create.email},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorMessages.EMAIL_ALREADY_EXISTS,
        )

    # 2. Prepare user object
    user_data = user_create.model_dump(exclude={"password", "lang"})
    db_obj = User(**user_data, hashed_password=get_password_hash(user_create.password))

    # 3. Call repository
    created_user = await create_user(session, db_obj)

    if current_user and request:
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.CREATE,
            resource_type=ResourceType.USER,
            resource_id=created_user.id,
            details={"email": created_user.email},
            request=request,
        )

    return created_user


async def get_user_service(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Get a user by ID or raise 404."""
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    return user


async def list_users_service(
    session: AsyncSession, skip: int = 0, limit: int = 100
) -> UsersPublic:
    """List users with pagination count."""
    users, count = await get_users_with_count(session, skip=skip, limit=limit)
    return UsersPublic(data=users, count=count)


async def update_user_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    user_id: uuid.UUID,
    user_update: UserUpdate | UserUpdateMe,
) -> UserPublic:
    """Update user information including password hashing if provided."""
    db_user = await get_user_service(session, user_id)

    # 1. Check email uniqueness if email is being updated
    if user_update.email and user_update.email != db_user.email:
        existing_user = await get_user_by_email(session, email=user_update.email)
        if existing_user:
            await log_activity(
                session=session,
                user_id=current_user.id,
                activity_type=ActivityType.UPDATE,
                resource_type=ResourceType.USER,
                status=ActivityStatus.FAILURE,
                details={"reason": "email_already_exists", "email": user_update.email},
                request=request,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorMessages.EMAIL_ALREADY_EXISTS,
            )

    # 2. Prepare update data
    update_dict = user_update.model_dump(exclude_unset=True)
    if "password" in update_dict:
        password = update_dict.pop("password")
        update_dict["hashed_password"] = get_password_hash(password)

    # 3. Call repository
    updated_user = await update_user(session, db_user, update_dict)

    await log_activity(
        session=session,
        user_id=current_user.id,  # Who is doing the update (admin or user themselves)
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=updated_user.id,  # Who is being updated
        details={"updated_fields": list(update_dict.keys())},
        request=request,
    )

    return UserPublic.model_validate(updated_user)
