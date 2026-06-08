"""Realtime propagation of RBAC permission changes over the account channel."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient

from app.core import realtime
from app.schemas.account import AccountEvent, AccountEventType
from app.schemas.admin_permission import Permission
from app.tests.admin.conftest import (
    get_user_id,
    promote_to_admin,
    register_and_verify,
)


class StubWebSocket:
    """Minimal WebSocket stand-in capturing the frames sent to it."""

    def __init__(self) -> None:
        """Initialise the stub with an empty captured-frame list."""
        self.frames: list[str] = []

    async def send_text(self, data: str) -> None:
        """Record an outbound text frame."""
        self.frames.append(data)


def test_account_topic_format():
    """The account feed topic is namespaced by the user id."""
    user_id = uuid.uuid4()
    assert realtime.account_topic(user_id) == f"account:{user_id}"


def test_account_event_serializes_to_type():
    """The account event serialises to its bare event-type discriminator."""
    event = AccountEvent(type=AccountEventType.PERMISSIONS_UPDATED)
    assert event.model_dump_json() == '{"type":"permissions_updated"}'


@pytest.mark.asyncio
async def test_permission_change_publishes_realtime_event(
    superadmin_client: AsyncClient,
):
    """Updating an admin's permissions pushes ``permissions_updated`` to them."""
    await register_and_verify(superadmin_client, "rtadmin@test.com")
    await promote_to_admin("rtadmin@test.com")
    user_id = await get_user_id("rtadmin@test.com")

    stub = StubWebSocket()
    topic = realtime.account_topic(uuid.UUID(user_id))
    await realtime.manager.connect(topic, stub)
    await realtime.start_realtime()
    try:
        await asyncio.sleep(0.1)
        response = await superadmin_client.patch(
            f"/admin/admins/{user_id}/permissions",
            json={"permissions": [Permission.STATS_READ.value]},
        )
        assert response.status_code == 200
        for _ in range(50):
            if stub.frames:
                break
            await asyncio.sleep(0.02)
    finally:
        await realtime.stop_realtime()
        await realtime.manager.disconnect(topic, stub)

    assert stub.frames
    assert AccountEventType.PERMISSIONS_UPDATED.value in stub.frames[0]
