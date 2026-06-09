"""Shared fixtures and helpers for the /support endpoint tests.

Reuses the admin test helpers (register/verify/login/promote) and adds a small
client factory so a single test can drive several authenticated identities at
once — needed for ownership checks (owner vs. other user) and the shared-queue
behaviour (two admins on one ticket).
"""

from collections.abc import Awaitable, Callable

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.tests.admin.conftest import (
    grant_all_permissions,
    login,
    promote_to_admin,
    register_and_verify,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"

ClientFactory = Callable[[], Awaitable[AsyncClient]]


@pytest_asyncio.fixture
async def client_factory() -> ClientFactory:
    """Yield a factory that builds fresh app-bound clients, closed on teardown.

    Each client has its own cookie jar, so callers can hold multiple logged-in
    identities simultaneously.
    """
    clients: list[AsyncClient] = []

    async def _make() -> AsyncClient:
        transport = ASGITransport(app=app)
        ac = AsyncClient(
            transport=transport, base_url=f"http://test{settings.API_V1_STR}"
        )
        clients.append(ac)
        return ac

    yield _make

    for ac in clients:
        await ac.aclose()


async def make_user_client(factory: ClientFactory, email: str) -> AsyncClient:
    """Build a verified, logged-in regular user client."""
    ac = await factory()
    await register_and_verify(ac, email)
    await login(ac, email)
    return ac


async def make_admin_client(factory: ClientFactory, email: str) -> AsyncClient:
    """Build a verified, logged-in admin client holding every RBAC permission.

    Stays role ``admin`` with all permissions granted so the support tests drive
    the admin ticket flows through the real per-permission gate.
    """
    ac = await factory()
    await register_and_verify(ac, email)
    await promote_to_admin(email)
    await grant_all_permissions(email)
    await login(ac, email)
    return ac


async def upload_png(
    client: AsyncClient,
    name: str = "a.png",
    category: str = "support_attachment",
) -> str:
    """Upload a PNG in the given category and return the created file id."""
    response = await client.post(
        "/upload",
        files={"file": (name, PNG_BYTES, "image/png")},
        data={"category": category},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def open_ticket(
    client: AsyncClient,
    subject: str = "Help me",
    body: str = "Something is broken",
    attachment_file_ids: list[str] | None = None,
) -> dict[str, object]:
    """Open a ticket and return the created ticket detail payload."""
    payload: dict[str, object] = {"subject": subject, "body": body}
    if attachment_file_ids is not None:
        payload["attachment_file_ids"] = attachment_file_ids
    response = await client.post("/support/tickets", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["ticket"]
