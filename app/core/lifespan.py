"""FastAPI lifespan: process-wide setup and teardown for shared resources."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.realtime import start_realtime, stop_realtime
from app.core.redis import close_redis, init_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialise and dispose shared resources (Redis, realtime) for the API."""
    await init_redis()
    await start_realtime()
    try:
        yield
    finally:
        await stop_realtime()
        await close_redis()
