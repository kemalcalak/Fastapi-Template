"""Tests for the notify use case and the notification emit hooks.

The use case is exercised directly against the realtime bridge (StubWebSocket
on the user's feed, mirroring the support realtime tests); the emit hooks are
driven through the real admin HTTP flows so a notification only ever appears
when the production code path created it.
"""

import asyncio
import uuid

import pytest

from app.core import realtime
from app.schemas.notification import NotificationEventType, NotificationType
from app.tests.admin.conftest import (
    login,
    promote_to_superadmin,
    register_and_verify,
)
from app.tests.notifications.conftest import (
    ClientFactory,
    get_user_id,
    seed_notification,
)
from app.tests.support.conftest import (
    make_admin_client,
    make_user_client,
    open_ticket,
)


class StubWebSocket:
    """Minimal WebSocket stand-in capturing the frames sent to it."""

    def __init__(self) -> None:
        """Initialise the stub with an empty captured-frame list."""
        self.frames: list[str] = []

    async def send_text(self, data: str) -> None:
        """Record an outbound text frame."""
        self.frames.append(data)


def test_notifications_topic_format():
    """The notification feed topic is namespaced by the user id."""
    uid = uuid.uuid4()
    assert realtime.notifications_topic(uid) == f"notifications:{uid}"


@pytest.mark.asyncio
async def test_notify_persists_and_publishes(client_factory: ClientFactory):
    """notify() stores the row and pushes it over the user's feed."""
    user = await make_user_client(client_factory, "u1@test.com")
    user_id = await get_user_id(user)

    ws = StubWebSocket()
    topic = realtime.notifications_topic(user_id)
    await realtime.manager.connect(topic, ws)
    await realtime.start_realtime()
    try:
        # Let the listener finish its psubscribe before publishing.
        await asyncio.sleep(0.1)
        await seed_notification(user_id, data={"subject": "Hello"})
        for _ in range(50):
            if ws.frames:
                break
            await asyncio.sleep(0.02)
    finally:
        await realtime.stop_realtime()
        await realtime.manager.disconnect(topic, ws)

    assert len(ws.frames) == 1
    assert NotificationEventType.NOTIFICATION_CREATED.value in ws.frames[0]

    body = (await user.get("/notifications")).json()
    assert body["total"] == 1
    assert body["data"][0]["data"]["subject"] == "Hello"


@pytest.mark.asyncio
async def test_admin_reply_notifies_owner(client_factory: ClientFactory):
    """An admin reply lands in the ticket owner's inbox with the ticket ref."""
    owner = await make_user_client(client_factory, "owner@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(owner, subject="Billing question")

    response = await admin.post(
        f"/admin/support/tickets/{ticket['id']}/messages",
        json={"body": "We are on it"},
    )
    assert response.status_code == 201, response.text

    body = (await owner.get("/notifications")).json()
    assert body["total"] == 1
    notification = body["data"][0]
    assert notification["type"] == NotificationType.SUPPORT_TICKET_REPLIED.value
    assert notification["data"]["ticket_id"] == ticket["id"]
    assert notification["data"]["subject"] == "Billing question"


@pytest.mark.asyncio
async def test_admin_self_reply_stays_silent(client_factory: ClientFactory):
    """An admin replying to their own ticket gets no self-notification."""
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(admin, subject="My own issue")

    response = await admin.post(
        f"/admin/support/tickets/{ticket['id']}/messages",
        json={"body": "Answering myself"},
    )
    assert response.status_code == 201, response.text

    assert (await admin.get("/notifications")).json()["total"] == 0


@pytest.mark.asyncio
async def test_status_change_notifies_owner(client_factory: ClientFactory):
    """A real status change lands in the owner's inbox with the new status."""
    owner = await make_user_client(client_factory, "owner@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(owner, subject="Login fails")

    response = await admin.patch(
        f"/admin/support/tickets/{ticket['id']}",
        json={"status": "closed"},
    )
    assert response.status_code == 200, response.text

    body = (await owner.get("/notifications")).json()
    assert body["total"] == 1
    notification = body["data"][0]
    assert notification["type"] == NotificationType.SUPPORT_TICKET_STATUS_CHANGED.value
    assert notification["data"]["status"] == "closed"
    assert notification["data"]["subject"] == "Login fails"


@pytest.mark.asyncio
async def test_priority_only_change_stays_silent(client_factory: ClientFactory):
    """Priority/assignment shuffles are admin-internal — no owner notification."""
    owner = await make_user_client(client_factory, "owner@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(owner)

    response = await admin.patch(
        f"/admin/support/tickets/{ticket['id']}",
        json={"priority": "high"},
    )
    assert response.status_code == 200, response.text

    assert (await owner.get("/notifications")).json()["total"] == 0


@pytest.mark.asyncio
async def test_permissions_update_notifies_admin(client_factory: ClientFactory):
    """Changing an admin's grants drops an RBAC notification in their inbox."""
    target = await make_admin_client(client_factory, "target@test.com")
    target_id = await get_user_id(target)

    superadmin = await client_factory()
    await register_and_verify(superadmin, "boss@test.com")
    await promote_to_superadmin("boss@test.com")
    await login(superadmin, "boss@test.com")

    response = await superadmin.patch(
        f"/admin/admins/{target_id}/permissions",
        json={"permissions": ["users:read"]},
    )
    assert response.status_code == 200, response.text

    body = (await target.get("/notifications")).json()
    assert body["total"] == 1
    notification = body["data"][0]
    assert notification["type"] == NotificationType.ADMIN_PERMISSIONS_CHANGED.value
    assert notification["data"]["action"] == "set_admin_permissions"
