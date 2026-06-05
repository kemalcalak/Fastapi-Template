"""Unit tests for the support realtime core and WebSocket auth gates.

The WebSocket endpoints are thin wrappers over three pieces of logic — the
``ConnectionManager``, the Redis pub/sub bridge, and the auth/ownership gates —
so we test those directly (fast and deterministic) rather than driving a real
socket through the ASGI stack.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.api.deps import get_ws_user
from app.core import realtime
from app.core.security import create_access_token
from app.models.user import User
from app.repositories.token_blacklist import add_token_to_blacklist
from app.schemas.support import RealtimeEvent, RealtimeEventType
from app.services.admin.support_service import ticket_exists_service
from app.services.support_service import can_user_access_ticket
from app.tests.conftest import TestingSessionLocal


class StubWebSocket:
    """Minimal WebSocket stand-in capturing the frames sent to it."""

    def __init__(self) -> None:
        self.frames: list[str] = []

    async def send_text(self, data: str) -> None:
        """Record an outbound text frame."""
        self.frames.append(data)


# --- ConnectionManager -----------------------------------------------------


@pytest.mark.asyncio
async def test_manager_broadcast_and_disconnect():
    """A connected socket receives broadcasts until it disconnects."""
    manager = realtime.ConnectionManager()
    ws = StubWebSocket()
    await manager.connect("ticket:x", ws)

    await manager.broadcast_local("ticket:x", "hello")
    assert ws.frames == ["hello"]

    await manager.disconnect("ticket:x", ws)
    await manager.broadcast_local("ticket:x", "after")
    assert ws.frames == ["hello"]


@pytest.mark.asyncio
async def test_manager_topic_isolation():
    """A broadcast reaches only the sockets on the same topic."""
    manager = realtime.ConnectionManager()
    on_ticket = StubWebSocket()
    on_admin = StubWebSocket()
    await manager.connect("ticket:x", on_ticket)
    await manager.connect("admin", on_admin)

    await manager.broadcast_local("ticket:x", "only-ticket")

    assert on_ticket.frames == ["only-ticket"]
    assert on_admin.frames == []


# --- Redis pub/sub bridge --------------------------------------------------


@pytest.mark.asyncio
async def test_publish_listener_roundtrip():
    """An event published to Redis reaches a locally-registered socket."""
    ticket_id = uuid.uuid4()
    topic = f"ticket:{ticket_id}"
    ws = StubWebSocket()
    await realtime.manager.connect(topic, ws)
    await realtime.start_realtime()
    try:
        # Let the listener finish its psubscribe before publishing.
        await asyncio.sleep(0.1)
        await realtime.publish(
            topic,
            RealtimeEvent(type=RealtimeEventType.MESSAGE_CREATED, ticket_id=ticket_id),
        )
        for _ in range(50):
            if ws.frames:
                break
            await asyncio.sleep(0.02)
    finally:
        await realtime.stop_realtime()
        await realtime.manager.disconnect(topic, ws)

    assert len(ws.frames) == 1
    assert RealtimeEventType.MESSAGE_CREATED.value in ws.frames[0]


# --- WebSocket auth / ownership gates --------------------------------------


async def _seed_user(email: str, role: str = "user") -> User:
    """Insert a minimal user row and return it."""
    async with TestingSessionLocal() as session:
        user = User(email=email, hashed_password="x", role=role, is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_get_ws_user_without_cookie_returns_none():
    """No cookie means no authenticated user."""
    websocket = SimpleNamespace(cookies={})
    async with TestingSessionLocal() as session:
        assert await get_ws_user(websocket, session) is None


@pytest.mark.asyncio
async def test_get_ws_user_with_valid_cookie_returns_user():
    """A valid access-token cookie resolves to its user."""
    user = await _seed_user("ws@test.com")
    token = create_access_token(user.id)
    websocket = SimpleNamespace(cookies={"access_token": token})
    async with TestingSessionLocal() as session:
        resolved = await get_ws_user(websocket, session)
    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_get_ws_user_with_blacklisted_token_returns_none():
    """A revoked token is rejected on the WebSocket too."""
    user = await _seed_user("ws@test.com")
    token = create_access_token(user.id)
    await add_token_to_blacklist(token)
    websocket = SimpleNamespace(cookies={"access_token": token})
    async with TestingSessionLocal() as session:
        assert await get_ws_user(websocket, session) is None


@pytest.mark.asyncio
async def test_can_user_access_ticket_gate():
    """Only the owner passes the per-ticket WebSocket gate."""
    from app.models.support import SupportTicket

    owner = await _seed_user("owner@test.com")
    other = await _seed_user("other@test.com")
    async with TestingSessionLocal() as session:
        ticket = SupportTicket(user_id=owner.id, subject="s", status="open")
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        ticket_id = ticket.id

    async with TestingSessionLocal() as session:
        assert await can_user_access_ticket(session, user=owner, ticket_id=ticket_id)
        assert not await can_user_access_ticket(
            session, user=other, ticket_id=ticket_id
        )
        assert not await can_user_access_ticket(
            session, user=owner, ticket_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_ticket_exists_service_gate():
    """The admin per-ticket WebSocket gate reflects ticket existence."""
    from app.models.support import SupportTicket

    owner = await _seed_user("owner@test.com")
    async with TestingSessionLocal() as session:
        ticket = SupportTicket(user_id=owner.id, subject="s", status="open")
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        ticket_id = ticket.id

    async with TestingSessionLocal() as session:
        assert await ticket_exists_service(session, ticket_id)
        assert not await ticket_exists_service(session, uuid.uuid4())
