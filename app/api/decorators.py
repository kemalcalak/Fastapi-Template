"""Cross-cutting route decorators.

Kept separate from ``api/deps.py`` because FastAPI ``Depends`` belong there
and mixing the two makes it harder to spot what is pure wrapper vs. DI.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import ParamSpec, TypeVar

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType
from app.services.user_activity_service import log_activity

_UNKNOWN_USER_ID = uuid.UUID(int=0)
"""Placeholder used when an unexpected failure fires before the caller is known.

Kept explicit so audit-log readers can recognise the sentinel.
"""

P = ParamSpec("P")
R = TypeVar("R")


def audit_unexpected_failure(
    *,
    activity_type: ActivityType,
    resource_type: ResourceType,
    endpoint: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Log unexpected failures of a route handler and re-raise the original error.

    ``HTTPException`` is passed through unchanged so FastAPI's own response
    logic still runs. Every other exception is recorded against the caller
    (or ``_UNKNOWN_USER_ID`` when we cannot yet identify them) and re-raised
    so the global exception handler can convert it to a 500 with the full
    traceback intact.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                session = _find_kwarg(kwargs, AsyncSession)
                request = _find_kwarg(kwargs, Request)
                current_user = _find_kwarg(kwargs, User)
                if session is not None:
                    await log_activity(
                        session=session,
                        user_id=current_user.id if current_user else _UNKNOWN_USER_ID,
                        activity_type=activity_type,
                        resource_type=resource_type,
                        status=ActivityStatus.FAILURE,
                        details={"error": str(exc), "endpoint": endpoint},
                        request=request,
                    )
                raise

        return wrapper

    return decorator


def _find_kwarg[T](kwargs: Mapping[str, object], expected_type: type[T]) -> T | None:
    """Return the first kwarg whose runtime type matches ``expected_type``.

    Route signatures vary (``session``/``db``, ``current_user`` may be
    ``CurrentUser`` or ``CurrentActiveUser``), so look up by type instead of
    name to keep the decorator generic.
    """
    for value in kwargs.values():
        if isinstance(value, expected_type):
            return value
    return None
