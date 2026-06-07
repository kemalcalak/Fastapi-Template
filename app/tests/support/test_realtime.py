"""Unit tests for the support realtime core and WebSocket auth gates.

The WebSocket endpoints are thin wrappers over three pieces of logic — the
``ConnectionManager``, the Redis pub/sub bridge, and the auth/ownership gates —
so we test those directly (fast and deterministic) rather than driving a real
socket through the ASGI stack.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from app.api.deps import get_ws_user
from app.core import realtime
from app.core.security import create_access_token, get_password_hash
from app.models.user import User
from app.repositories.token_blacklist import add_token_to_blacklist
from app.schemas.support import RealtimeEvent, RealtimeEventType
from app.services.admin.support_service import ticket_exists_service
from app.services.support_service import can_user_access_ticket_service
from app.tests.conftest import TestingSessionLocal


class StubWebSocket:
    """Minimal WebSocket stand-in capturing the frames sent to it."""

    def __init__(self) -> None:
        """Initialise the stub with an empty captured-frame list."""
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


def test_user_topic_format():
    """The user-feed topic is namespaced by the user id."""
    uid = uuid.uuid4()
    assert realtime.user_topic(uid) == f"user:{uid}"


@pytest.mark.asyncio
async def test_publish_feeds_reaches_admin_and_owner():
    """publish_feeds fans one event out to both the admin queue and the owner."""
    owner_id = uuid.uuid4()
    admin_ws = StubWebSocket()
    owner_ws = StubWebSocket()
    owner_feed = realtime.user_topic(owner_id)
    await realtime.manager.connect("admin", admin_ws)
    await realtime.manager.connect(owner_feed, owner_ws)
    await realtime.start_realtime()
    try:
        await asyncio.sleep(0.1)
        await realtime.publish_feeds(
            owner_id,
            RealtimeEvent(
                type=RealtimeEventType.TICKET_UPDATED, ticket_id=uuid.uuid4()
            ),
        )
        for _ in range(50):
            if admin_ws.frames and owner_ws.frames:
                break
            await asyncio.sleep(0.02)
    finally:
        await realtime.stop_realtime()
        await realtime.manager.disconnect("admin", admin_ws)
        await realtime.manager.disconnect(owner_feed, owner_ws)

    assert len(admin_ws.frames) == 1
    assert len(owner_ws.frames) == 1


# --- Multiplex command handling --------------------------------------------


async def _allow(_ticket_id: uuid.UUID) -> bool:
    """Authorize callback that always grants the subscription."""
    return True


async def _deny(_ticket_id: uuid.UUID) -> bool:
    """Authorize callback that always refuses the subscription."""
    return False


def test_parse_ticket_topic():
    """Only well-formed ``ticket:{uuid}`` topics resolve to an id."""
    tid = uuid.uuid4()
    assert realtime._parse_ticket_topic(f"ticket:{tid}") == tid
    assert realtime._parse_ticket_topic("admin") is None
    assert realtime._parse_ticket_topic(f"user:{tid}") is None
    assert realtime._parse_ticket_topic("ticket:not-a-uuid") is None


@pytest.mark.asyncio
async def test_disconnect_all_clears_every_topic():
    """disconnect_all removes a socket from every topic it joined."""
    manager = realtime.ConnectionManager()
    ws = StubWebSocket()
    await manager.connect("admin", ws)
    await manager.connect("ticket:x", ws)

    await manager.disconnect_all(ws)

    await manager.broadcast_local("admin", "a")
    await manager.broadcast_local("ticket:x", "b")
    assert ws.frames == []


@pytest.mark.asyncio
async def test_handle_command_subscribe_authorized_then_unsubscribe():
    """An authorized subscribe joins the ticket topic; unsubscribe leaves it."""
    ws = StubWebSocket()
    ticket_id = uuid.uuid4()
    topic = f"ticket:{ticket_id}"
    try:
        await realtime._handle_command(
            ws, json.dumps({"action": "subscribe", "topic": topic}), _allow
        )
        await realtime.manager.broadcast_local(topic, "hit")
        assert ws.frames == ["hit"]

        await realtime._handle_command(
            ws, json.dumps({"action": "unsubscribe", "topic": topic}), _allow
        )
        await realtime.manager.broadcast_local(topic, "after")
        assert ws.frames == ["hit"]
    finally:
        await realtime.manager.disconnect_all(ws)


@pytest.mark.asyncio
async def test_handle_command_subscribe_denied():
    """A denied subscribe never joins the topic."""
    ws = StubWebSocket()
    topic = f"ticket:{uuid.uuid4()}"
    try:
        await realtime._handle_command(
            ws, json.dumps({"action": "subscribe", "topic": topic}), _deny
        )
        await realtime.manager.broadcast_local(topic, "hit")
        assert ws.frames == []
    finally:
        await realtime.manager.disconnect_all(ws)


@pytest.mark.asyncio
async def test_handle_command_ignores_feed_topics_and_bad_input():
    """Non-ticket topics and malformed frames are ignored (no subscription)."""
    ws = StubWebSocket()
    try:
        # Feed topics are server-controlled — a client can't self-subscribe.
        await realtime._handle_command(
            ws, json.dumps({"action": "subscribe", "topic": "admin"}), _allow
        )
        await realtime.manager.broadcast_local("admin", "x")
        # Malformed frames must not raise.
        await realtime._handle_command(ws, "not-json", _allow)
        await realtime._handle_command(ws, json.dumps(["a"]), _allow)
        assert ws.frames == []
    finally:
        await realtime.manager.disconnect_all(ws)


# --- WebSocket auth / ownership gates --------------------------------------


async def _seed_user(email: str, role: str = "user") -> User:
    """Insert a minimal user row and return it."""
    async with TestingSessionLocal() as session:
        user = User(
            email=email,
            hashed_password=get_password_hash("test-password"),
            role=role,
            is_active=True,
        )
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
        assert await can_user_access_ticket_service(
            session, user=owner, ticket_id=ticket_id
        )
        assert not await can_user_access_ticket_service(
            session, user=other, ticket_id=ticket_id
        )
        assert not await can_user_access_ticket_service(
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
