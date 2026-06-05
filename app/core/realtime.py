"""Realtime fan-out for support tickets.

A thin in-process registry of WebSocket connections (``ConnectionManager``)
sits behind a Redis pub/sub bridge. Services ``publish()`` an event to a Redis
channel; a per-process listener task receives it and delivers it to the local
WebSockets subscribed to that topic. Going through Redis means an event raised
in one worker reaches clients connected to any worker.

Topics are plain strings:
  * ``ticket:{uuid}`` — the thread of a single ticket (its owner + viewing admin)
  * ``admin``         — the global admin feed (new tickets, status changes)

The Redis channel is the topic prefixed with ``support:``.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

from app.core.redis import get_redis
from app.schemas.support import RealtimeEvent

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "support:"
_CHANNEL_PATTERN = f"{_CHANNEL_PREFIX}*"


class ConnectionManager:
    """In-process map of topic -> set of live WebSocket connections."""

    def __init__(self) -> None:
        self._topics: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, topic: str, websocket: WebSocket) -> None:
        """Register an already-accepted WebSocket under a topic."""
        async with self._lock:
            self._topics.setdefault(topic, set()).add(websocket)

    async def disconnect(self, topic: str, websocket: WebSocket) -> None:
        """Remove a WebSocket from a topic, dropping the topic when empty."""
        async with self._lock:
            connections = self._topics.get(topic)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._topics.pop(topic, None)

    async def broadcast_local(self, topic: str, data: str) -> None:
        """Send a raw text frame to every local WebSocket on ``topic``.

        Iterates a snapshot so a send-triggered disconnect can't mutate the set
        mid-loop. Failed sockets are pruned rather than aborting the broadcast.
        """
        async with self._lock:
            connections = list(self._topics.get(topic, ()))
        if not connections:
            return

        dead: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_text(data)
            except Exception:  # noqa: BLE001 - a broken socket must not stop fan-out
                dead.append(websocket)

        for websocket in dead:
            await self.disconnect(topic, websocket)


manager = ConnectionManager()

_listener_task: asyncio.Task[None] | None = None


async def publish(topic: str, event: RealtimeEvent) -> None:
    """Publish an event to all subscribers of ``topic`` across processes."""
    await get_redis().publish(f"{_CHANNEL_PREFIX}{topic}", event.model_dump_json())


async def _listen() -> None:
    """Bridge Redis pub/sub messages to local WebSocket connections."""
    pubsub = get_redis().pubsub()
    await pubsub.psubscribe(_CHANNEL_PATTERN)
    try:
        async for raw in pubsub.listen():
            if raw.get("type") != "pmessage":
                continue
            channel = raw["channel"]
            topic = channel[len(_CHANNEL_PREFIX) :]
            await manager.broadcast_local(topic, raw["data"])
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - listener must survive transient errors
        logger.exception("Support realtime listener crashed")
    finally:
        await pubsub.punsubscribe(_CHANNEL_PATTERN)
        await pubsub.aclose()


async def start_realtime() -> None:
    """Start the background Redis -> WebSocket listener task."""
    global _listener_task
    if _listener_task is None:
        _listener_task = asyncio.create_task(_listen())


async def stop_realtime() -> None:
    """Cancel the listener task and wait for it to unwind."""
    global _listener_task
    if _listener_task is not None:
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
        _listener_task = None
