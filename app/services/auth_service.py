import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import send_email
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.realtime import account_topic, publish_safe
from app.core.security import (
    aget_password_hash,
    averify_password,
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token_payload,
    generate_new_account_token,
    get_password_hash,
    verify_new_account_token,
    verify_password_reset_token,
)
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.login_attempts import (
    clear_login_attempts,
    is_login_locked,
    register_failed_login,
)
from app.repositories.token_blacklist import (
    add_token_to_blacklist,
    is_token_blacklisted,
)
from app.repositories.user import get_user_by_email, get_user_by_id, update_user
from app.repositories.user_session import (
    create_session,
    flag_sessions_revoked,
    get_session_by_id,
    revoke_all_sessions,
    revoke_session,
    rotate_session_jti,
)
from app.schemas.account import AccountEvent, AccountEventType
from app.schemas.msg import Message
from app.schemas.token import AuthTokens, RefreshedTokens
from app.schemas.user import (
    Language,
    SystemRole,
    UpdatePassword,
    UserCreate,
    UserPublic,
    UserRegister,
)
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType
from app.services.user_service import create_user_service
from app.use_cases.log_activity import log_activity
from app.utils.email_templates import (
    generate_account_locked_email,
    generate_email_verification_email,
    generate_password_reset_email,
)


async def register_service(
    request: Request, session: AsyncSession, user_register: UserRegister
) -> UserPublic:
    """Register a user, audit the event, and send the verification email.

    Builds the user from a restricted ``UserRegister`` payload and forces the
    privileged fields (``role``, ``is_active``, ``is_verified``) to safe values
    so a self-service registrant can never escalate to admin/superadmin or
    self-verify. Privileged user creation goes through the admin flow instead.
    """
    safe_user = UserCreate(
        email=user_register.email,
        password=user_register.password,
        first_name=user_register.first_name,
        last_name=user_register.last_name,
        title=user_register.title,
        lang=user_register.lang,
        role=SystemRole.USER,
        is_active=True,
        is_verified=False,
    )
    user = await create_user_service(
        request=request, session=session, user_create=safe_user, current_user=None
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
        lang=user_register.lang,
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


async def _notify_account_locked(user: User) -> None:
    """Email the user that their account was just locked (best-effort)."""
    lock_minutes = max(1, settings.LOGIN_LOCKOUT_SECONDS // 60)
    email_data = generate_account_locked_email(
        project_name=settings.PROJECT_NAME,
        lock_minutes=lock_minutes,
        lang=settings.DEFAULT_LANGUAGE,
    )
    await send_email(
        to=user.email,
        subject=email_data["subject"],
        body=email_data["html"],
        plain_text=email_data["plain_text"],
        user_id=str(user.id),
        is_html=True,
    )


async def authenticate(
    request: Request | None, session: AsyncSession, email: str, password: str
) -> User:
    """
    Authenticate a user by email and password.
    Returns the user object if successful, raises 401 otherwise.
    Combined check for security (timing attacks).
    """
    # Account lockout guard: reject early (423) while a temporary lock is active
    # so even a correct password cannot be used during the cooldown.
    lock_ttl = await is_login_locked(email)
    if lock_ttl > 0:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=ErrorMessages.ACCOUNT_LOCKED,
            headers={"Retry-After": str(lock_ttl)},
        )

    user = await get_user_by_email(session, email=email)

    # Always run verify_password so the response time does not leak whether
    # the email exists (email enumeration guard).
    hashed = user.hashed_password if user else _DUMMY_PASSWORD_HASH
    password_ok = await averify_password(password, hashed)

    if not user or not password_ok:
        if user and request:
            await log_activity(
                session=session,
                user_id=user.id,
                activity_type=ActivityType.LOGIN,
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                status_code=status.HTTP_401_UNAUTHORIZED,
                details={"reason": "invalid_password", "email": email},
                request=request,
            )

        # Count the failure; the threshold-crossing attempt locks the account.
        locked_now = await register_failed_login(email)
        if locked_now:
            if user:
                await _notify_account_locked(user)
                if request:
                    await log_activity(
                        session=session,
                        user_id=user.id,
                        activity_type=ActivityType.LOGIN,
                        resource_type=ResourceType.AUTH,
                        status=ActivityStatus.FAILURE,
                        status_code=status.HTTP_423_LOCKED,
                        details={"reason": "account_locked", "email": email},
                        request=request,
                    )
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=ErrorMessages.ACCOUNT_LOCKED,
                headers={"Retry-After": str(settings.LOGIN_LOCKOUT_SECONDS)},
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_CREDENTIALS,
        )

    # Correct password: reset the failed-attempt counter so a legitimate login
    # never accumulates toward a lockout.
    await clear_login_attempts(email)

    # Admin-suspended accounts are permanently locked out. This guard must run
    # before the grace-window fall-through below, otherwise a suspended user
    # would still receive tokens.
    if user.suspended_at is not None:
        if request:
            await log_activity(
                session=session,
                user_id=user.id,
                activity_type=ActivityType.LOGIN,
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                status_code=status.HTTP_403_FORBIDDEN,
                details={"reason": "account_suspended", "email": email},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.ACCOUNT_SUSPENDED,
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


def _refresh_claims(refresh_token: str) -> dict:
    """Decode a just-minted refresh token's claims (jti + exp for the session row)."""
    claims = decode_token_payload(refresh_token, expected_type="refresh")
    if claims is None:  # pragma: no cover - we minted the token one line above
        raise RuntimeError("freshly minted refresh token failed to decode")
    return claims


async def _open_session(
    request: Request | None,
    session: AsyncSession,
    user: User,
    session_id: uuid.UUID,
    refresh_token: str,
) -> None:
    """Persist the UserSession row backing a freshly issued token pair.

    Device metadata is truncated to the column sizes so a hostile header can
    never fail the insert.
    """
    claims = _refresh_claims(refresh_token)
    user_agent = request.headers.get("user-agent") if request else None
    ip_address = request.client.host if request and request.client else None
    await create_session(
        session,
        UserSession(
            id=session_id,
            user_id=user.id,
            refresh_jti=claims["jti"],
            user_agent=user_agent[:512] if user_agent else None,
            ip_address=ip_address[:45] if ip_address else None,
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        ),
    )


async def login_service(
    request: Request, session: AsyncSession, email: str, password: str
) -> AuthTokens:
    """
    Orchestrate the login process: authenticate user and generate JWT tokens.

    Every successful login opens a ``UserSession`` row whose id rides in both
    tokens as the ``sid`` claim, enabling per-device session management.
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

    session_id = uuid.uuid4()
    access_token = create_access_token(user.id, session_id=session_id)
    refresh_token = create_refresh_token(user.id, session_id=session_id)
    await _open_session(request, session, user, session_id, refresh_token)

    return AuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserPublic.model_validate(user),
        message=SuccessMessages.LOGIN_SUCCESS,
    )


async def refresh_token_service(
    request: Request | None, session: AsyncSession, refresh_token: str
) -> RefreshedTokens:
    """
    Validate the refresh token and rotate the session credentials.

    On success the presented refresh token is revoked and a fresh access +
    refresh pair is issued. Replaying the old (now-blacklisted) refresh token
    is rejected by the blacklist guard below; should the blacklist ever lose
    state (Redis flush), the session-jti match catches the replay instead and
    revokes the whole session as compromised.
    """
    claims = decode_token_payload(refresh_token, expected_type="refresh")
    # Tokens without a session binding (pre-session deploys) are rejected —
    # the holder simply logs in again and gets a session-bound pair.
    if not claims or not claims.get("sid"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )
    user_id = claims["sub"]

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
                status_code=status.HTTP_401_UNAUTHORIZED,
                details={"reason": "token_blacklisted"},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Refresh works for users in the deletion grace window too (so they stay
    # on the cancel-deletion page without repeatedly re-authenticating). Only
    # hard-deleted and admin-suspended users are blocked.
    user = await get_user_by_id(session, parsed_user_id)
    if not user:
        if request:
            await log_activity(
                session=session,
                user_id=parsed_user_id,
                activity_type=ActivityType.LOGIN,
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                status_code=status.HTTP_403_FORBIDDEN,
                details={"reason": "user_deleted"},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.USER_INACTIVE,
        )

    if user.suspended_at is not None:
        if request:
            await log_activity(
                session=session,
                user_id=parsed_user_id,
                activity_type=ActivityType.LOGIN,
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                status_code=status.HTTP_403_FORBIDDEN,
                details={"reason": "account_suspended"},
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.ACCOUNT_SUSPENDED,
        )

    # Session guard: the binding row must still be live.
    session_id = uuid.UUID(claims["sid"])
    user_session = await get_session_by_id(session, session_id)
    if (
        user_session is None
        or user_session.revoked_at is not None
        or user_session.user_id != parsed_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Replay guard: a rotated-away jti means this token was already spent.
    # Someone is holding a stale copy — kill the whole session.
    if user_session.refresh_jti != claims["jti"]:
        await revoke_session(session, session_id=session_id)
        await flag_sessions_revoked([session_id])
        if request:
            await log_activity(
                session=session,
                user_id=parsed_user_id,
                activity_type=ActivityType.LOGIN,
                resource_type=ResourceType.AUTH,
                status=ActivityStatus.FAILURE,
                status_code=status.HTTP_401_UNAUTHORIZED,
                details={
                    "reason": "refresh_token_replay",
                    "session_id": str(session_id),
                },
                request=request,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
        )

    # Rotate: revoke the presented refresh token and mint a fresh pair bound
    # to the same session, then record the new jti/expiry on the row.
    await _revoke_token(refresh_token)

    new_access_token = create_access_token(user_id, session_id=session_id)
    new_refresh_token = create_refresh_token(user_id, session_id=session_id)
    new_claims = _refresh_claims(new_refresh_token)
    await rotate_session_jti(
        session,
        session_id=session_id,
        refresh_jti=new_claims["jti"],
        expires_at=datetime.fromtimestamp(new_claims["exp"], tz=UTC),
    )

    return RefreshedTokens(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        message=SuccessMessages.LOGIN_SUCCESS,
    )


async def _revoke_token(token: str | None) -> None:
    """Blacklist a token if present and not already revoked.

    The guard avoids redundant writes when the same token is revoked twice
    (e.g. a double logout) without raising.
    """
    if token and not await is_token_blacklisted(token):
        await add_token_to_blacklist(token)


async def _close_session(session: AsyncSession, sid: str | None) -> None:
    """Revoke the session row for ``sid`` and flag it in Redis (best-effort)."""
    if not sid:
        return
    try:
        session_id = uuid.UUID(sid)
    except ValueError:
        return
    await revoke_session(session, session_id=session_id)
    await flag_sessions_revoked([session_id])


async def logout_service(
    request: Request | None,
    session: AsyncSession,
    refresh_token: str | None,
    access_token: str | None = None,
) -> None:
    """
    Invalidate the session by blacklisting both the refresh and access tokens.

    Revoking the access token too closes the window where a stolen access
    token would otherwise stay valid until its own expiry after logout. The
    backing ``UserSession`` row is revoked as well so the device disappears
    from the active-sessions list.
    """
    await _revoke_token(access_token)

    # Resolve the session binding from whichever token is available.
    claims = None
    if refresh_token:
        claims = decode_token_payload(refresh_token, expected_type="refresh")
    if claims is None and access_token:
        claims = decode_token_payload(access_token)
    if claims:
        await _close_session(session, claims.get("sid"))

    if refresh_token:
        await _revoke_token(refresh_token)

        # Log success if possible
        if claims and request:
            try:
                parsed_user_id = uuid.UUID(claims["sub"])
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
    if not user or not user.is_active:
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
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )

    hashed_password = await aget_password_hash(new_password)

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
    if not user or not user.is_active:
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
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> Message:
    """
    Change user password after verifying current password.

    On success every session of the user is revoked — the current one (its
    access and refresh tokens are blacklisted, forcing re-authentication) and
    every other device, so a credential thief is logged out everywhere the
    moment the owner rotates the password.
    """
    if not await averify_password(
        update_password.current_password, current_user.hashed_password
    ):
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.UPDATE,
            resource_type=ResourceType.AUTH,
            status=ActivityStatus.FAILURE,
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"reason": "invalid_current_password"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.INVALID_CURRENT_PASSWORD,
        )

    hashed_password = await aget_password_hash(update_password.new_password)
    await update_user(session, current_user, {"hashed_password": hashed_password})

    # Revoke the current session so the change forces a fresh login and any
    # token captured before the change stops working immediately.
    await _revoke_token(access_token)
    await _revoke_token(refresh_token)

    # Kill every session of the account (this device and all others): a
    # password rotation must evict anyone holding stolen credentials. The live
    # broadcast drops other devices' open tabs to login at once, mirroring the
    # session-service revoke paths, instead of waiting for their next request.
    revoked = await revoke_all_sessions(session, user_id=current_user.id)
    if revoked:
        await flag_sessions_revoked([s.id for s in revoked])
        await publish_safe(
            account_topic(current_user.id),
            AccountEvent(type=AccountEventType.SESSIONS_REVOKED),
        )

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.AUTH,
        details={"action": "password_changed"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.PASSWORD_CHANGE_SUCCESS)
