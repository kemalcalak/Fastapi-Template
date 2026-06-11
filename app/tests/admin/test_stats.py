"""End-to-end tests for the GET /admin/stats dashboard endpoint."""

import pytest
from httpx import AsyncClient

from app.tests.admin.conftest import register_and_verify


@pytest.mark.asyncio
async def test_stats_requires_admin(regular_client: AsyncClient):
    """A non-admin must receive 403 from /admin/stats."""
    response = await regular_client.get("/admin/stats")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_stats_without_auth_returns_401(client: AsyncClient):
    """An unauthenticated caller must receive 401, not 403."""
    response = await client.get("/admin/stats")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_stats_returns_expected_counts(admin_client: AsyncClient):
    """Stats payload reflects the seeded admin plus verified and unverified users."""
    await register_and_verify(admin_client, "alice@test.com")
    await register_and_verify(admin_client, "bob@test.com")
    await admin_client.post(
        "/auth/register",
        json={
            "email": "unverified@test.com",
            "password": "Password123!",
            "first_name": "U",
            "last_name": "V",
            "title": "T",
        },
    )

    response = await admin_client.get("/admin/stats")
    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {
        "users_total",
        "users_active",
        "users_verified",
        "users_admins",
        "activities_total",
    }
    assert body["users_total"] >= 4
    assert body["users_active"] >= 4
    assert body["users_verified"] >= 3
    assert body["users_verified"] < body["users_total"]
    assert body["users_admins"] >= 1
    assert body["activities_total"] >= 1
