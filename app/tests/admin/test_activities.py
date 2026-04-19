"""End-to-end tests for /admin/activities endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User
from app.models.user_activity import UserActivity
from app.tests.admin.conftest import (
    get_user_id,
    login,
    register_and_verify,
)
from app.tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_list_user_activities_returns_that_users_rows(admin_client: AsyncClient):
    """Per-user activities endpoint must return only the targeted user's rows."""
    await register_and_verify(admin_client, "acts@test.com")
    user_id = await get_user_id("acts@test.com")
    await login(admin_client, "acts@test.com")  # generates a LOGIN activity
    # Log back in as the admin so the admin cookie is reinstated.
    await login(admin_client, "admin@test.com")

    response = await admin_client.get(f"/admin/users/{user_id}/activities")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["user_id"] == user_id for item in body["data"])


@pytest.mark.asyncio
async def test_list_activities_global_filters(admin_client: AsyncClient):
    """Global activities endpoint paginates all rows and supports filters."""
    # Seed a failure row so the status filter has something to find.
    async with TestingSessionLocal() as session:
        admin = (
            (await session.execute(select(User).where(User.email == "admin@test.com")))
            .scalars()
            .one()
        )
        session.add(
            UserActivity(
                user_id=admin.id,
                activity_type="login",
                resource_type="auth",
                details={"reason": "invalid_password"},
                status="failure",
            )
        )
        await session.commit()

    response = await admin_client.get("/admin/activities?limit=100")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1

    response = await admin_client.get("/admin/activities?status=failure")
    body = response.json()
    assert all(item["status"] == "failure" for item in body["data"])
