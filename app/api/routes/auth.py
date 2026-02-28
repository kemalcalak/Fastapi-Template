import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.schemas.msg import Message
from app.schemas.token import LoginResponse, Token
from app.schemas.user import (
    ForgotPassword,
    NewPassword,
    UserCreate,
    VerifyEmail,
)
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType
from app.services.auth_service import (
    login_service,
    logout_service,
    recover_password_service,
    refresh_token_service,
    register_service,
    resend_verification_service,
    reset_password_service,
    verify_email_service,
)
from app.services.user_activity_service import log_activity

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
    try:
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
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),
            activity_type=ActivityType.LOGIN,
            resource_type=ResourceType.AUTH,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/login"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


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


@router.post("/logout", response_model=Message, status_code=status.HTTP_200_OK)
async def logout(
    request: Request, response: Response, session: SessionDep
) -> Message:
    """
    Clear refresh token cookie and invalidate token in the blacklist.
    """
    refresh_token = request.cookies.get("refresh_token")
    try:
        if refresh_token:
            await logout_service(
                request=request, session=session, refresh_token=refresh_token
            )

        response.delete_cookie(
            key="refresh_token",
            path=f"{settings.API_V1_STR}/auth/refresh",
        )
        return Message(success=True, message=SuccessMessages.LOGOUT_SUCCESS)
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


@router.post("/register", response_model=Message, status_code=status.HTTP_201_CREATED)
async def register_user(
    request: Request, session: SessionDep, user_in: UserCreate
) -> Message:
    """
    Register a new user.
    """
    try:
        await register_service(request=request, session=session, user_create=user_in)
        return Message(success=True, message=SuccessMessages.REGISTER_SUCCESS)
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),
            activity_type=ActivityType.CREATE,
            resource_type=ResourceType.USER,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/register"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.post("/verify-email", response_model=Message, status_code=status.HTTP_200_OK)
async def verify_email(
    request: Request, session: SessionDep, body: VerifyEmail
) -> Message:
    """
    Verify user email using the token sent via email.
    """
    try:
        return await verify_email_service(
            request=request, session=session, token=body.token, lang=body.lang
        )
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),
            activity_type=ActivityType.UPDATE,
            resource_type=ResourceType.USER,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/verify-email"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.post("/forgot-password", response_model=Message, status_code=status.HTTP_200_OK)
async def forgot_password(
    request: Request, session: SessionDep, body: ForgotPassword
) -> Message:
    """
    Send an email with a password reset link.
    """
    try:
        return await recover_password_service(
            request=request, session=session, email=body.email, lang=body.lang
        )
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),
            activity_type=ActivityType.UPDATE,
            resource_type=ResourceType.USER,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/forgot-password"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.post("/reset-password", response_model=Message, status_code=status.HTTP_200_OK)
async def reset_password(
    request: Request, session: SessionDep, body: NewPassword
) -> Message:
    """
    Reset password using a token.
    """
    try:
        return await reset_password_service(
            request=request,
            session=session,
            token=body.token,
            new_password=body.new_password,
        )
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),
            activity_type=ActivityType.UPDATE,
            resource_type=ResourceType.USER,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/reset-password"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.post(
    "/resend-verification", response_model=Message, status_code=status.HTTP_200_OK
)
async def resend_verification(
    request: Request, session: SessionDep, body: ForgotPassword
) -> Message:
    """
    Resend verification email.
    """
    try:
        return await resend_verification_service(
            request=request, session=session, email=body.email, lang=body.lang
        )
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=uuid.UUID(int=0),
            activity_type=ActivityType.UPDATE,
            resource_type=ResourceType.USER,
            status=ActivityStatus.FAILURE,
            details={"error": str(e), "endpoint": "/resend-verification"},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)
