"""End-to-end tests for the user-facing /notifications endpoints.

Covers listing/ordering, the unread counter, pagination and the unread-only
filter, per-user isolation, and the read-marking flows with their ownership
guards.
"""

import uuid

import pytest

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.schemas.notification import NotificationType
from app.tests.notifications.conftest import (
    ClientFactory,
    get_user_id,
    make_user_client,
    seed_notification,
)


@pytest.mark.asyncio
async def test_list_requires_auth(client_factory: ClientFactory):
    """The notification endpoints reject unauthenticated callers."""
    anonymous = await client_factory()

    assert (await anonymous.get("/notifications")).status_code == 401
    assert (await anonymous.get("/notifications/unread-count")).status_code == 401
    assert (await anonymous.post("/notifications/read-all")).status_code == 401


@pytest.mark.asyncio
async def test_list_empty(client_factory: ClientFactory):
    """A fresh user has an empty inbox and a zero badge."""
    user = await make_user_client(client_factory, "u1@test.com")

    response = await user.get("/notifications")
    assert response.status_code == 200
    assert response.json() == {"data": [], "total": 0, "skip": 0, "limit": 50}

    response = await user.get("/notifications/unread-count")
    assert response.status_code == 200
    assert response.json() == {"unread_count": 0}


@pytest.mark.asyncio
async def test_list_newest_first_and_unread_count(client_factory: ClientFactory):
    """Listing returns seeded notifications newest first; all count as unread."""
    user = await make_user_client(client_factory, "u1@test.com")
    user_id = await get_user_id(user)
    await seed_notification(user_id, data={"subject": "first"})
    await seed_notification(user_id, data={"subject": "second"})

    response = await user.get("/notifications")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [row["data"]["subject"] for row in body["data"]] == ["second", "first"]
    assert all(row["read_at"] is None for row in body["data"])

    response = await user.get("/notifications/unread-count")
    assert response.json() == {"unread_count": 2}


@pytest.mark.asyncio
async def test_list_pagination_and_unread_only(client_factory: ClientFactory):
    """skip/limit page through the inbox; unread_only hides read entries."""
    user = await make_user_client(client_factory, "u1@test.com")
    user_id = await get_user_id(user)
    seeded = [await seed_notification(user_id) for _ in range(3)]

    response = await user.get("/notifications?skip=0&limit=2")
    body = response.json()
    assert body["total"] == 3
    assert len(body["data"]) == 2
    assert body["limit"] == 2

    await user.post(f"/notifications/{seeded[0].id}/read")

    response = await user.get("/notifications?unread_only=true")
    body = response.json()
    assert body["total"] == 2
    assert all(row["read_at"] is None for row in body["data"])


@pytest.mark.asyncio
async def test_list_only_my_notifications(client_factory: ClientFactory):
    """Users only ever see their own inbox."""
    user = await make_user_client(client_factory, "u1@test.com")
    other = await make_user_client(client_factory, "u2@test.com")
    await seed_notification(await get_user_id(user), data={"subject": "mine"})
    await seed_notification(await get_user_id(other), data={"subject": "theirs"})

    body = (await user.get("/notifications")).json()

    assert body["total"] == 1
    assert body["data"][0]["data"]["subject"] == "mine"


@pytest.mark.asyncio
async def test_mark_read_is_idempotent(client_factory: ClientFactory):
    """Marking read stamps read_at once; a repeat keeps the original stamp."""
    user = await make_user_client(client_factory, "u1@test.com")
    seeded = await seed_notification(await get_user_id(user))

    response = await user.post(f"/notifications/{seeded.id}/read")
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == SuccessMessages.NOTIFICATION_READ
    first_read_at = body["data"]["read_at"]
    assert first_read_at is not None

    response = await user.post(f"/notifications/{seeded.id}/read")
    assert response.status_code == 200
    assert response.json()["data"]["read_at"] == first_read_at

    response = await user.get("/notifications/unread-count")
    assert response.json() == {"unread_count": 0}


@pytest.mark.asyncio
async def test_mark_read_not_owned_rejected(client_factory: ClientFactory):
    """A user cannot mark someone else's notification as read (IDOR guard)."""
    owner = await make_user_client(client_factory, "owner@test.com")
    other = await make_user_client(client_factory, "other@test.com")
    seeded = await seed_notification(await get_user_id(owner))

    response = await other.post(f"/notifications/{seeded.id}/read")

    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.NOTIFICATION_ACCESS_DENIED


@pytest.mark.asyncio
async def test_mark_read_missing_rejected(client_factory: ClientFactory):
    """Marking a non-existent notification returns 404."""
    user = await make_user_client(client_factory, "u1@test.com")

    response = await user.post(f"/notifications/{uuid.uuid4()}/read")

    assert response.status_code == 404
    assert response.json()["error"] == ErrorMessages.NOTIFICATION_NOT_FOUND


@pytest.mark.asyncio
async def test_mark_all_read(client_factory: ClientFactory):
    """read-all stamps every unread entry and reports how many it touched."""
    user = await make_user_client(client_factory, "u1@test.com")
    user_id = await get_user_id(user)
    seeded = [
        await seed_notification(
            user_id, notification_type=NotificationType.ADMIN_PERMISSIONS_CHANGED
        )
        for _ in range(3)
    ]
    await user.post(f"/notifications/{seeded[0].id}/read")

    response = await user.post("/notifications/read-all")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == SuccessMessages.NOTIFICATIONS_ALL_READ
    assert body["updated"] == 2

    assert (await user.get("/notifications/unread-count")).json() == {"unread_count": 0}
