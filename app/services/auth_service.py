

import uuid
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    verify_refresh_token,
)
from app.models.user import User
from app.repositories.user import get_user_by_email, get_user_by_id
from app.repositories.token_blacklist import is_token_blacklisted, add_token_to_blacklist
from app.schemas.token import AuthTokens, Token
from app.schemas.user import UserCreate, UserPublic
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.user_activity_service import log_activity
from app.services.user_service import create_user_service


async def register_service(
    request: Request, session: AsyncSession, user_create: UserCreate
) -> UserPublic:
    """
    Handle public user registration.
    Orchestrates user creation and any post-registration tasks.
    """
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
    return UserPublic.model_validate(user)


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """
    Authenticate a user by email and password.
    Returns the user object if successful, raises 401 otherwise.
    Combined check for security (timing attacks).
    """
    user = await get_user_by_email(session, email=email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_PASSWORD,
        )

    if not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_PASSWORD,
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.USER_INACTIVE,
        )

    return user


async def login_service(
    request: Request, session: AsyncSession, email: str, password: str
) -> AuthTokens:
    """
    Orchestrate the login process: authenticate user and generate JWT tokens.
    Simplified token creation relying on security component defaults.
    """
    user = await authenticate(session, email=email, password=password)

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
    )


async def refresh_token_service(session: AsyncSession, refresh_token: str) -> Token:
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

    # Check if the token is revoked
    if await is_token_blacklisted(session, refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Convert user_id to UUID
    try:
        parsed_user_id = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Check if user exists and is active
    user = await get_user_by_id(session, parsed_user_id)
    if not user or not user.is_active or user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.USER_INACTIVE,
        )

    return Token(access_token=create_access_token(user_id))


async def logout_service(session: AsyncSession, refresh_token: str | None) -> None:
    """
    Invalidates a refresh token by adding it to the blacklist.
    """
    if refresh_token:
        # Check if it was already blacklisted to avoid unique constraint errors
        is_blacklisted = await is_token_blacklisted(session, refresh_token)
        if not is_blacklisted:
            await add_token_to_blacklist(session, refresh_token)
