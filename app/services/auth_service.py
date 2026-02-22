from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.models.user import User
from app.repositories.user import get_user_by_email
from app.schemas.token import Token
from app.schemas.user import UserCreate
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.user_activity_service import log_activity
from app.services.user_service import create_user_service


async def register_service(
    request: Request, session: AsyncSession, user_create: UserCreate
) -> User:
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
    return user



async def authenticate(session: AsyncSession, email: str, password: str) -> Any:
    """
    Authenticate a user by email and password.
    Returns the user object if successful, raises 401 otherwise.
    Combined check for security (timing attacks).
    """
    user = await get_user_by_email(session, email=email)

    if not user or not verify_password(password, user.hashed_password):
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
) -> Token:
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

    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )

