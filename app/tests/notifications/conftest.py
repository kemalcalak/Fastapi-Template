"""Shared fixtures and helpers for the /notifications endpoint tests.

Reuses the support test client factory (multiple logged-in identities per
test) and adds seeding straight through the real ``notify`` use case, so every
test row went through the same code path production uses.
"""

import uuid

from httpx import AsyncClient

from app.models.notification import Notification
from app.schemas.common import JsonValue
from app.schemas.notification import NotificationType
from app.tests.conftest import TestingSessionLocal
from app.tests.support.conftest import (  # noqa: F401 - re-exported fixture
    ClientFactory,
    client_factory,
    make_user_client,
)
from app.use_cases.notify import notify

__all__ = ["ClientFactory", "make_user_client", "get_user_id", "seed_notification"]


async def get_user_id(client: AsyncClient) -> uuid.UUID:
    """Return the authenticated client's own user id via /users/me."""
    response = await client.get("/users/me")
    assert response.status_code == 200, response.text
    return uuid.UUID(response.json()["id"])


async def seed_notification(
    user_id: uuid.UUID,
    *,
    type: NotificationType = NotificationType.SUPPORT_TICKET_REPLIED,
    data: dict[str, JsonValue] | None = None,
) -> Notification:
    """Persist one notification for ``user_id`` through the real use case."""
    async with TestingSessionLocal() as session:
        return await notify(session, user_id=user_id, type=type, data=data)
