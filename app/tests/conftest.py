from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import fakeredis.aioredis as fakeredis
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.api.deps import get_db
from app.core import redis as redis_module
from app.core.db import Base
from app.main import app

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
    """Enforce FKs in SQLite so ON DELETE SET NULL/CASCADE fire like Postgres."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)


async def override_get_db():
    """Yield a test-bound async DB session."""
    async with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(scope="function", autouse=True)
async def create_test_database():
    """Create a fresh database for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def fake_redis():
    """Swap the real Redis client for an in-process fake during tests."""
    client = fakeredis.FakeRedis(decode_responses=True)
    redis_module.set_redis_for_testing(client)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()
        redis_module.set_redis_for_testing(None)


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """Async HTTP client wired to the FastAPI app."""
    from app.core.config import settings

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url=f"http://test{settings.API_V1_STR}"
    ) as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def mock_email_send():
    """Prevent real SMTP connections from any caller during tests.

    Patches both the source (``app.core.email.send_email``) and the
    re-export used by the auth service. Callers that import the function
    directly still hit the mock.
    """
    with (
        patch("app.core.email.send_email", new_callable=AsyncMock) as core_mock,
        patch("app.services.auth_service.send_email", new=core_mock),
        patch("app.services.user_service.send_email", new=core_mock),
        patch("app.services.admin.user_service.send_email", new=core_mock),
    ):
        yield core_mock


@pytest_asyncio.fixture(autouse=True)
async def mock_email_validation():
    """Bypass MX / disposable-domain lookups during tests.

    Tests use invented domains like ``test.com`` that have no MX records,
    and the register flow now rejects those by default. Patch at every
    import site so both direct and re-exported callers hit the mock.
    """
    with (
        patch("app.core.email.check_mx_record", new=AsyncMock(return_value=True)),
        patch(
            "app.services.user_service.check_mx_record",
            new=AsyncMock(return_value=True),
        ),
        patch("app.core.email.is_disposable_email", new=AsyncMock(return_value=False)),
        patch(
            "app.services.user_service.is_disposable_email",
            new=AsyncMock(return_value=False),
        ),
    ):
        yield


@pytest_asyncio.fixture(autouse=True)
async def mock_cloudinary():
    """Stub Cloudinary so upload/delete never hit the network during tests.

    Yields the upload/delete mocks so tests can assert calls. Each upload
    returns a unique ``public_id`` to mirror real, non-colliding assets.
    """
    from app.core.storage import UploadResult

    def _fake_upload(_content: bytes, **_kwargs: object) -> UploadResult:
        return UploadResult(
            url="https://cdn.test/img.png", public_id=f"uploads/{uuid4()}"
        )

    upload_mock = AsyncMock(side_effect=_fake_upload)
    delete_mock = AsyncMock(return_value=True)
    with (
        patch("app.core.storage.upload_file", new=upload_mock),
        patch("app.core.storage.delete_file", new=delete_mock),
    ):
        yield SimpleNamespace(upload=upload_mock, delete=delete_mock)
