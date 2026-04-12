from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentActiveUser, SessionDep
from app.core.config import settings
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.rate_limit import rate_limit_public, rate_limit_strict
from app.schemas.msg import Message
from app.schemas.token import (
    CookieLoginResponse,
    CookieRefreshResponse,
)
from app.schemas.user import (
    ForgotPassword,
    NewPassword,
    UpdatePassword,
    UserCreate,
    VerifyEmail,
)
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.auth_service import (
    change_password_service,
    login_service,
    logout_service,
    recover_password_service,
    refresh_token_service,
    register_service,
    resend_verification_service,
    reset_password_service,
    verify_email_service,
)

router = APIRouter()

# The refresh cookie is limited to the refresh endpoint only so it is never
# sent on unrelated requests. This path must match for both set_cookie and
# delete_cookie calls or the cookie cannot be cleared.
_REFRESH_COOKIE_PATH = f"{settings.API_V1_STR}/auth/refresh"
_COOKIE_SECURE = settings.ENVIRONMENT != "local"


def _set_access_cookie(response: Response, token: str) -> None:
    """Write the access token as an HttpOnly cookie for the whole API."""
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Write the refresh token as an HttpOnly, path-scoped cookie."""
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    """Remove both auth cookies using the same paths they were set with."""
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path=_REFRESH_COOKIE_PATH)


@router.post(
    "/login", response_model=CookieLoginResponse, status_code=status.HTTP_200_OK
)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.LOGIN,
    resource_type=ResourceType.AUTH,
    endpoint="/login",
)
async def login_access_token(
    response: Response,
    request: Request,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> CookieLoginResponse:
    """OAuth2 compatible token login, get an access token for future requests."""
    result = await login_service(
        request=request,
        session=session,
        email=form_data.username,
        password=form_data.password,
    )
    _set_access_cookie(response, result.access_token)
    _set_refresh_cookie(response, result.refresh_token)
    return CookieLoginResponse(user=result.user, message=result.message)


@router.post(
    "/refresh", response_model=CookieRefreshResponse, status_code=status.HTTP_200_OK
)
@rate_limit_public("30/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.LOGIN,
    resource_type=ResourceType.AUTH,
    endpoint="/refresh",
)
async def refresh_token(
    request: Request,
    response: Response,
    session: SessionDep,
) -> CookieRefreshResponse:
    """Refresh access token using the refresh token from cookie."""
    refresh_token_cookie = request.cookies.get("refresh_token")
    if not refresh_token_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.REFRESH_TOKEN_MISSING,
        )

    result = await refresh_token_service(
        request=request, session=session, refresh_token=refresh_token_cookie
    )
    _set_access_cookie(response, result.access_token)
    return CookieRefreshResponse(message=result.message)


@router.post("/logout", response_model=Message, status_code=status.HTTP_200_OK)
@audit_unexpected_failure(
    activity_type=ActivityType.LOGOUT,
    resource_type=ResourceType.AUTH,
    endpoint="/logout",
)
async def logout(request: Request, response: Response, session: SessionDep) -> Message:
    """Clear refresh token cookie and invalidate token in the blacklist."""
    refresh_token_cookie = request.cookies.get("refresh_token")
    if refresh_token_cookie:
        await logout_service(
            request=request, session=session, refresh_token=refresh_token_cookie
        )
    _clear_auth_cookies(response)
    return Message(success=True, message=SuccessMessages.LOGOUT_SUCCESS)


@router.post("/register", response_model=Message, status_code=status.HTTP_201_CREATED)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.CREATE,
    resource_type=ResourceType.USER,
    endpoint="/register",
)
async def register_user(
    request: Request, session: SessionDep, user_in: UserCreate
) -> Message:
    """Register a new user."""
    await register_service(request=request, session=session, user_create=user_in)
    return Message(success=True, message=SuccessMessages.REGISTER_SUCCESS)


@router.post("/verify-email", response_model=Message, status_code=status.HTTP_200_OK)
@rate_limit_public("10/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/verify-email",
)
async def verify_email(
    request: Request, session: SessionDep, body: VerifyEmail
) -> Message:
    """Verify user email using the token sent via email."""
    return await verify_email_service(
        request=request, session=session, token=body.token
    )


@router.post("/forgot-password", response_model=Message, status_code=status.HTTP_200_OK)
@rate_limit_strict("3/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/forgot-password",
)
async def forgot_password(
    request: Request, session: SessionDep, body: ForgotPassword
) -> Message:
    """Send an email with a password reset link."""
    return await recover_password_service(
        request=request, session=session, email=body.email, lang=body.lang
    )


@router.post("/reset-password", response_model=Message, status_code=status.HTTP_200_OK)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/reset-password",
)
async def reset_password(
    request: Request, session: SessionDep, body: NewPassword
) -> Message:
    """Reset password using a token."""
    return await reset_password_service(
        request=request,
        session=session,
        token=body.token,
        new_password=body.new_password,
    )


@router.post(
    "/resend-verification", response_model=Message, status_code=status.HTTP_200_OK
)
@rate_limit_strict("3/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/resend-verification",
)
async def resend_verification(
    request: Request, session: SessionDep, body: ForgotPassword
) -> Message:
    """Resend verification email."""
    return await resend_verification_service(
        request=request, session=session, email=body.email, lang=body.lang
    )


@router.patch(
    "/change-password", response_model=Message, status_code=status.HTTP_200_OK
)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.AUTH,
    endpoint="/change-password",
)
async def change_password(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    body: UpdatePassword,
) -> Message:
    """Change user password while logged in."""
    return await change_password_service(
        request=request,
        session=session,
        current_user=current_user,
        update_password=body,
    )
