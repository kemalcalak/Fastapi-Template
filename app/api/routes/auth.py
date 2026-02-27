from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.schemas.token import LoginResponse, Token
from app.schemas.user import UserCreate, UserPublic
from app.schemas.user_activity import ActivityType, ResourceType, ActivityStatus
from app.services.user_activity_service import log_activity
from app.services.auth_service import (
    login_service,
    refresh_token_service,
    register_service,
    logout_service,
)

router = APIRouter()


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login_access_token(
    response: Response,
    request: Request,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> LoginResponse:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    result = await login_service(
        request=request,
        session=session,
        email=form_data.username,
        password=form_data.password,
    )

    # Set refresh token in HttpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT != "local",
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=f"{settings.API_V1_STR}/auth/refresh",
    )

    return LoginResponse(
        access_token=result.access_token,
        user=result.user,
    )


@router.post("/refresh", response_model=Token, status_code=status.HTTP_200_OK)
async def refresh_token(
    request: Request,
    session: SessionDep,
) -> Token:
    """
    Refresh access token using the refresh token from cookie.
    """
    refresh_token_cookie = request.cookies.get("refresh_token")
    if not refresh_token_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.REFRESH_TOKEN_MISSING,
        )

    try:
        return await refresh_token_service(
            request=request, session=session, refresh_token=refresh_token_cookie
        )
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),  # Unknown user
            activity_type=ActivityType.LOGIN,
            resource_type=ResourceType.AUTH,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/refresh"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: Request, response: Response, session: SessionDep) -> dict[str, str]:
    """
    Clear refresh token cookie and invalidate token in the blacklist.
    """
    refresh_token = request.cookies.get("refresh_token")
    try:
        if refresh_token:
            await logout_service(request=request, session=session, refresh_token=refresh_token)

        response.delete_cookie(
            key="refresh_token",
            path=f"{settings.API_V1_STR}/auth/refresh",
        )
        return {"message": SuccessMessages.LOGOUT_SUCCESS}
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),  # Unknown user
            activity_type=ActivityType.LOGOUT,
            resource_type=ResourceType.AUTH,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/logout"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register_user(
    request: Request, session: SessionDep, user_in: UserCreate
) -> UserPublic:
    """
    Register a new user.
    """
    return await register_service(request=request, session=session, user_create=user_in)

