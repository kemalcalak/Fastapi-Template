import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import send_email
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    generate_new_account_token,
    get_password_hash,
    verify_new_account_token,
    verify_password,
    verify_password_reset_token,
    verify_refresh_token,
)
from app.models.user import User
from app.repositories.token_blacklist import (
    add_token_to_blacklist,
    is_token_blacklisted,
)
from app.repositories.user import get_user_by_email, get_user_by_id, update_user
from app.schemas.msg import Message
from app.schemas.token import AuthTokens, Token
from app.schemas.user import Language, UpdatePassword, UserCreate, UserPublic
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType
from app.services.user_activity_service import log_activity
from app.services.user_service import create_user_service
from app.utils.email_templates import (
    generate_email_verification_email,
    generate_password_reset_email,
)


async def register_service(
    request: Request, session: AsyncSession, user_create: UserCreate
) -> UserPublic:
    """Register a user, audit the event, and send the verification email."""
    user = await create_user_service(
        request=request, session=session, user_create=user_create, current_user=None
    )
    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.CREATE,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        details={"email": user.email},
        request=request,
    )

    # Generate verification token
    verification_token = generate_new_account_token(user.email)

    verify_url = f"{settings.FRONTEND_HOST}/verify-email?token={verification_token}"

    email_data = generate_email_verification_email(
        verify_link=verify_url,
        project_name=settings.PROJECT_NAME,
        lang=user_create.lang,
    )

    await send_email(
        to=user.email,
        subject=email_data["subject"],
        body=email_data["html"],
        plain_text=email_data["plain_text"],
        user_id=str(user.id),
        is_html=True,
    )

    return UserPublic.model_validate(user)


# Pre-computed bcrypt hash of a random string used to keep authentication
# timing constant when the supplied email does not exist in the database.
# Regenerating on module import is enough — the value itself is not sensitive.
_DUMMY_PASSWORD_HASH = get_password_hash("unused-timing-safe-placeholder")


async def authenticate(
    request: Request | None, session: AsyncSession, email: str, password: str
) -> User:
    """
    Authenticate a user by email and password.
    Returns the user object if successful, raises 401 otherwise.
    Combined check for security (timing attacks).
    """
    user = await get_user_by_email(session, email=email)

    # Always run verify_password so the response time does not leak whether
    # the email exists (email enumeration guard).
    hashed = user.hashed_password if user else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(password, hashed)

    if not user or not password_ok:
        if user and request:
            await log_activity(
                session=session,
                user_id=user.id,
                activity_type=ActivityType.LOGIN,
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                details={"reason": "invalid_password", "email": email},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_CREDENTIALS,
        )

    # Accounts in the deletion grace window (is_active=False + deletion_scheduled_at)
    # are allowed to log in so the frontend can render the "cancel deletion" page.
    # The ``get_current_active_user`` dep still blocks them from regular endpoints.

    if not getattr(user, "is_verified", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.EMAIL_NOT_VERIFIED,
        )

    return user


async def login_service(
    request: Request, session: AsyncSession, email: str, password: str
) -> AuthTokens:
    """
    Orchestrate the login process: authenticate user and generate JWT tokens.
    Simplified token creation relying on security component defaults.
    """
    user = await authenticate(
        request=request, session=session, email=email, password=password
    )

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.LOGIN,
        resource_type=ResourceType.AUTH,
        details={"email": user.email},
        request=request,
    )

    return AuthTokens(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=UserPublic.model_validate(user),
        message=SuccessMessages.LOGIN_SUCCESS,
    )


async def refresh_token_service(
    request: Request | None, session: AsyncSession, refresh_token: str
) -> Token:
    """
    Validate refresh token and return a new access token.
    Checks if token is blacklisted and the user is still active.
    """
    user_id = verify_refresh_token(refresh_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Convert user_id to UUID early to use it in logging
    try:
        parsed_user_id = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Check if the token is revoked
    if await is_token_blacklisted(refresh_token):
        if request:
            await log_activity(
                session=session,
                user_id=parsed_user_id,
                activity_type=ActivityType.LOGIN,  # or READ
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                details={"reason": "token_blacklisted"},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Refresh works for users in the deletion grace window too (so they stay
    # on the cancel-deletion page without repeatedly re-authenticating). Only
    # hard-deleted users are blocked.
    user = await get_user_by_id(session, parsed_user_id)
    if not user or user.is_deleted:
        if request:
            await log_activity(
                session=session,
                user_id=parsed_user_id,
                activity_type=ActivityType.LOGIN,
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                details={"reason": "user_deleted"},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.USER_INACTIVE,
        )

    return Token(
        access_token=create_access_token(user_id), message=SuccessMessages.LOGIN_SUCCESS
    )


async def logout_service(
    request: Request | None, session: AsyncSession, refresh_token: str | None
) -> None:
    """
    Invalidates a refresh token by adding it to the blacklist.
    """
    if refresh_token:
        # Check if it was already blacklisted to avoid unique constraint errors
        is_blacklisted = await is_token_blacklisted(refresh_token)
        if not is_blacklisted:
            await add_token_to_blacklist(refresh_token)

        # Log success if possible
        user_id = verify_refresh_token(refresh_token)
        if user_id and request:
            try:
                parsed_user_id = uuid.UUID(user_id)
                await log_activity(
                    session=session,
                    user_id=parsed_user_id,
                    activity_type=ActivityType.LOGOUT,
                    resource_type=ResourceType.AUTH,
                    request=request,
                )
            except ValueError:
                pass


async def verify_email_service(
    request: Request, session: AsyncSession, token: str
) -> Message:
    # Check if token is blacklisted
    if await is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    email = verify_new_account_token(token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.INVALID_VERIFICATION_TOKEN,
        )

    user = await get_user_by_email(session, email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )

    if getattr(user, "is_verified", False):
        return Message(success=True, message=SuccessMessages.EMAIL_VERIFIED)

    await update_user(session, user, {"is_verified": True})

    # Blacklist the token after successful use
    await add_token_to_blacklist(token)

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        details={"email_verified": True},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.EMAIL_VERIFIED)


async def recover_password_service(
    request: Request, session: AsyncSession, email: str, lang: str = Language.EN
) -> Message:
    user = await get_user_by_email(session, email)

    # We always return success so as not to leak emails
    if not user or not user.is_active or user.is_deleted:
        return Message(success=True, message=SuccessMessages.PASSWORD_RESET_SENT)

    token = create_password_reset_token(email)

    reset_url = f"{settings.FRONTEND_HOST}/reset-password?token={token}"

    email_data = generate_password_reset_email(
        reset_link=reset_url, project_name=settings.PROJECT_NAME, lang=lang
    )

    await send_email(
        to=user.email,
        subject=email_data["subject"],
        body=email_data["html"],
        plain_text=email_data["plain_text"],
        user_id=str(user.id),
        is_html=True,
    )

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        details={"action": "password_recovery_requested"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.PASSWORD_RESET_SENT)


async def reset_password_service(
    request: Request, session: AsyncSession, token: str, new_password: str
) -> Message:
    # Check if token is blacklisted
    if await is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    email = verify_password_reset_token(token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.INVALID_VERIFICATION_TOKEN,
        )

    user = await get_user_by_email(session, email)
    if not user or not user.is_active or user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )

    hashed_password = get_password_hash(new_password)

    await update_user(session, user, {"hashed_password": hashed_password})

    # Blacklist the token after successful use
    await add_token_to_blacklist(token)

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        details={"action": "password_reset_completed"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.PASSWORD_RESET_SUCCESS)


async def resend_verification_service(
    request: Request, session: AsyncSession, email: str, lang: str = Language.EN
) -> Message:
    user = await get_user_by_email(session, email)

    # We always return success so as not to leak emails
    if not user or not user.is_active or user.is_deleted:
        return Message(success=True, message=SuccessMessages.VERIFICATION_EMAIL_SENT)

    if getattr(user, "is_verified", False):
        return Message(success=True, message=SuccessMessages.EMAIL_VERIFIED)

    # Generate verification token
    verification_token = generate_new_account_token(user.email)

    verify_url = f"{settings.FRONTEND_HOST}/verify-email?token={verification_token}"

    email_data = generate_email_verification_email(
        verify_link=verify_url,
        project_name=settings.PROJECT_NAME,
        lang=lang,
    )

    await send_email(
        to=user.email,
        subject=email_data["subject"],
        body=email_data["html"],
        plain_text=email_data["plain_text"],
        user_id=str(user.id),
        is_html=True,
    )

    await log_activity(
        session=session,
        user_id=user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        details={"action": "verification_email_resend_requested"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.VERIFICATION_EMAIL_SENT)


async def change_password_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    update_password: UpdatePassword,
) -> Message:
    """
    Change user password after verifying current password.
    """
    if not verify_password(
        update_password.current_password, current_user.hashed_password
    ):
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.UPDATE,
            resource_type=ResourceType.AUTH,
            status=ActivityStatus.FAILURE,
            details={"reason": "invalid_current_password"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.INVALID_CURRENT_PASSWORD,
        )

    hashed_password = get_password_hash(update_password.new_password)
    await update_user(session, current_user, {"hashed_password": hashed_password})

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        details={"action": "password_changed"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.PASSWORD_CHANGE_SUCCESS)
