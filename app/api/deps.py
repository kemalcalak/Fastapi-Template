import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.messages.error_message import ErrorMessages
from app.core.security import verify_token
from app.models.user import User
from app.repositories.admin.permission import has_permission
from app.repositories.token_blacklist import is_token_blacklisted
from app.repositories.user import get_user_by_id
from app.schemas.admin_permission import Permission
from app.schemas.token import TokenPayload
from app.schemas.user import SystemRole

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    bearer_token: Annotated[str | None, Depends(reusable_oauth2)] = None,
) -> User:
    """Resolve the JWT to a User, allowing accounts in the deletion grace window.

    This intentionally does NOT reject ``is_active=False`` users — that check
    moved to ``get_current_active_user`` so deactivated users can still hit
    ``/users/me`` and ``/users/me/reactivate`` during the grace period.
    """
    token = request.cookies.get("access_token") or bearer_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        if await is_token_blacklisted(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ErrorMessages.INVALID_TOKEN,
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_subject = verify_token(token)
        if token_subject is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ErrorMessages.INVALID_TOKEN,
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_data = TokenPayload(sub=token_subject)
    except (ValidationError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_id(db, user_id=uuid.UUID(token_data.sub))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ErrorMessages.USER_NOT_FOUND
        )
    return user


def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require the caller's account to be active (not in deletion grace)."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.USER_INACTIVE,
        )
    return current_user


def get_current_admin_user(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Require an active admin or superadmin — the admin-panel access gate."""
    if current_user.role not in (SystemRole.ADMIN, SystemRole.SUPERADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.INSUFFICIENT_PERMISSIONS,
        )
    return current_user


def get_current_superadmin(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Require an active superadmin (admin management is superadmin-only)."""
    if current_user.role != SystemRole.SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.ONLY_SUPERADMIN_ALLOWED,
        )
    return current_user


async def get_ws_user(websocket: WebSocket, db: AsyncSession) -> User | None:
    """Authenticate a WebSocket from its ``access_token`` cookie.

    Mirrors ``get_current_user`` but returns ``None`` instead of raising, so the
    caller can close the socket with an application code. Cookie-only: a browser
    sends the auth cookie on the WebSocket handshake automatically, while bearer
    headers are awkward to set on ``WebSocket`` clients.
    """
    token = websocket.cookies.get("access_token")
    if not token:
        return None

    try:
        if await is_token_blacklisted(token):
            return None
        token_subject = verify_token(token)
        if token_subject is None:
            return None
        token_data = TokenPayload(sub=token_subject)
    except (ValidationError, ValueError):
        return None

    user = await get_user_by_id(db, user_id=uuid.UUID(token_data.sub))
    if user is None or not user.is_active:
        return None
    return user


# Type aliases for dependency injection
SessionDep = Annotated[AsyncSession, Depends(get_db)]
# reusable_oauth2 uses auto_error=False, so the dependency may resolve to None.
TokenDep = Annotated[str | None, Depends(reusable_oauth2)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentActiveUser = Annotated[User, Depends(get_current_active_user)]
CurrentAdminUser = Annotated[User, Depends(get_current_admin_user)]
CurrentSuperAdmin = Annotated[User, Depends(get_current_superadmin)]


async def user_has_permission(
    session: AsyncSession, user: User, permission: Permission
) -> bool:
    """Return whether ``user`` may exercise ``permission`` (superadmin bypass).

    The admin-role gate lives here so the answer is safe even if a non-admin
    ever reaches it — a demoted account whose grant rows linger, or a caller
    that skips ``CurrentAdminUser``. Superadmins always pass; plain admins must
    hold the grant; anyone else is denied. This is the non-raising counterpart
    to ``ensure_permission`` for callers that branch instead of aborting (e.g. a
    WebSocket handshake that closes with a policy code).
    """
    if user.role == SystemRole.SUPERADMIN:
        return True
    if user.role != SystemRole.ADMIN:
        return False
    return await has_permission(session, user.id, permission)


async def ensure_permission(
    session: AsyncSession, user: User, permission: Permission
) -> None:
    """Raise 403 unless ``user`` is a superadmin or an admin holding the grant.

    Shared by ``require_permission`` and the payload-aware authorization
    dependencies in the admin routes, so the superadmin-bypass rule and the
    grant lookup live in exactly one place.
    """
    if not await user_has_permission(session, user, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorMessages.INSUFFICIENT_PERMISSIONS,
        )


def require_permission(permission: Permission) -> Callable[..., Awaitable[User]]:
    """Build a dependency that enforces a single RBAC permission.

    The returned dependency inherits auth, active-account, and admin-role checks
    from ``CurrentAdminUser``. Superadmins bypass the grant lookup; plain admins
    must hold ``permission`` in ``admin_permission`` or receive a 403.
    """

    async def _require(admin: CurrentAdminUser, session: SessionDep) -> User:
        await ensure_permission(session, admin, permission)
        return admin

    return _require


async def _request_body_fields(request: Request) -> set[str]:
    """Return the top-level keys present in the request's JSON body.

    Authorization only needs to know which fields the caller is attempting to
    set, so a non-JSON or malformed body yields an empty set and the endpoint's
    own validation handles the error. Starlette caches the body, so reading it
    here does not consume it before the route parses the payload.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - any parse failure means "no fields seen"
        return set()
    return set(body) if isinstance(body, dict) else set()


def require_permissions(
    base: Permission,
    *,
    conditional: dict[str, Permission] | None = None,
) -> Callable[..., Awaitable[User]]:
    """Build a dependency enforcing ``base`` plus field-conditional permissions.

    ``base`` is always required. Each ``field -> permission`` in ``conditional``
    is additionally required when that field appears in the JSON request body —
    e.g. ``{"role": USERS_ROLE}`` demands ``users:role`` only when the update
    touches ``role``. Reading body keys instead of a typed model keeps the
    factory reusable across endpoints with different payload schemas.
    Superadmins bypass every check via ``ensure_permission``.
    """
    field_map = conditional or {}

    async def _require(
        request: Request, admin: CurrentAdminUser, session: SessionDep
    ) -> User:
        await ensure_permission(session, admin, base)
        if field_map:
            present = await _request_body_fields(request)
            for field, permission in field_map.items():
                if field in present:
                    await ensure_permission(session, admin, permission)
        return admin

    return _require
