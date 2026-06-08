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

    response = await admin_client.post("/admin/activities/search", json={"limit": 100})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1

    response = await admin_client.post(
        "/admin/activities/search", json={"status": "failure"}
    )
    body = response.json()
    assert all(item["status"] == "failure" for item in body["data"])


@pytest.mark.asyncio
async def test_activity_rows_embed_the_actor(admin_client: AsyncClient):
    """Each activity row carries the acting user's identity (email/name)."""
    async with TestingSessionLocal() as session:
        admin = (
            (await session.execute(select(User).where(User.email == "admin@test.com")))
            .scalars()
            .one()
        )
        admin_id = str(admin.id)
        session.add(
            UserActivity(
                user_id=admin.id,
                activity_type="login",
                resource_type="auth",
                details={},
                status="success",
            )
        )
        await session.commit()

    response = await admin_client.post("/admin/activities/search", json={"limit": 100})
    assert response.status_code == 200
    row = next(r for r in response.json()["data"] if r["user_id"] == admin_id)
    assert row["user"] is not None
    assert row["user"]["email"] == "admin@test.com"


@pytest.mark.asyncio
async def test_search_activities_by_actor_name_or_email(admin_client: AsyncClient):
    """The user_search filter matches activities by the actor's name/email."""
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
                details={},
                status="success",
            )
        )
        await session.commit()

    match = await admin_client.post(
        "/admin/activities/search", json={"user_search": "admin@test"}
    )
    assert match.status_code == 200
    assert match.json()["total"] >= 1

    miss = await admin_client.post(
        "/admin/activities/search", json={"user_search": "no-such-actor-xyz"}
    )
    assert miss.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_activities_status_code_filter(admin_client: AsyncClient):
    """Global activities endpoint exposes status_code and filters on it."""
    async with TestingSessionLocal() as session:
        admin = (
            (await session.execute(select(User).where(User.email == "admin@test.com")))
            .scalars()
            .one()
        )
        session.add_all(
            [
                UserActivity(
                    user_id=admin.id,
                    activity_type="login",
                    resource_type="auth",
                    details={"reason": "invalid_password"},
                    status="failure",
                    status_code=401,
                ),
                UserActivity(
                    user_id=admin.id,
                    activity_type="create",
                    resource_type="user",
                    details={"reason": "email_already_exists"},
                    status="failure",
                    status_code=409,
                ),
            ]
        )
        await session.commit()

    response = await admin_client.post(
        "/admin/activities/search", json={"status_code": 401, "limit": 100}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"], "expected at least one row with status_code 401"
    assert all(item["status_code"] == 401 for item in body["data"])
