import pytest
from httpx import AsyncClient

from app.core.messages.success_message import SuccessMessages


@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """
    Returns an authenticated client for a newly created test user.
    """
    # Register a new user
    await client.post(
        "/auth/register",
        json={
            "email": "user_test@test.com",
            "password": "password123",
            "first_name": "Test",
            "last_name": "User",
            "title": "Tester",
        },
    )

    from sqlalchemy import update

    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    # Verify the user directly in DB to test the rest of the flow
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.email == "user_test@test.com")
            .values(is_verified=True)
        )
        await session.commit()

    # Login — access_token is set as HttpOnly cookie; httpx stores and forwards it automatically
    response = await client.post(
        "/auth/login",
        data={
            "username": "user_test@test.com",
            "password": "password123",
        },
    )
    assert response.status_code == 200
    assert response.cookies.get("access_token") is not None
    return client


@pytest.mark.asyncio
async def test_read_user_me(auth_client: AsyncClient):
    response = await auth_client.get("/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "user_test@test.com"
    assert data["first_name"] == "Test"
    assert data["last_name"] == "User"
    assert data["is_active"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_update_user_me(auth_client: AsyncClient):
    response = await auth_client.patch(
        "/users/me",
        json={
            "first_name": "Updated",
            "last_name": "Name",
            "title": "Senior Tester",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == SuccessMessages.USER_UPDATED
    assert data["user"]["first_name"] == "Updated"
    assert data["user"]["last_name"] == "Name"
    assert data["user"]["title"] == "Senior Tester"

    # Verify updates persisted
    response = await auth_client.get("/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "Updated"


@pytest.mark.asyncio
async def test_delete_user_me_wrong_password_rejected(auth_client: AsyncClient):
    """Wrong password must not start the grace window."""
    response = await auth_client.request(
        "DELETE",
        url="/users/me",
        json={"password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_user_me_schedules_deletion(auth_client: AsyncClient):
    """Correct password deactivates the account and schedules deletion."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.core.config import settings
    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    response = await auth_client.request(
        "DELETE",
        url="/users/me",
        json={"password": "password123"},
    )
    assert response.status_code == 200

    async with TestingSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "user_test@test.com")
        )
        user = result.scalars().one()
        assert user.is_active is False
        assert user.is_deleted is False
        assert user.deactivated_at is not None
        assert user.deletion_scheduled_at is not None
        delta = user.deletion_scheduled_at - user.deactivated_at
        # Allow 1 second skew between repository timestamps.
        assert abs(
            delta - timedelta(days=settings.ACCOUNT_DELETION_GRACE_DAYS)
        ) < timedelta(seconds=2)


@pytest.mark.asyncio
async def test_delete_user_me_twice_returns_400(auth_client: AsyncClient):
    """Second deactivate attempt while already pending must fail fast."""
    first = await auth_client.request(
        "DELETE", url="/users/me", json={"password": "password123"}
    )
    assert first.status_code == 200

    # After deactivate, cookies are cleared by the route. Re-login to get
    # fresh credentials — deactivated users are allowed to log back in.
    await auth_client.post(
        "/auth/login",
        data={"username": "user_test@test.com", "password": "password123"},
    )

    second = await auth_client.request(
        "DELETE", url="/users/me", json={"password": "password123"}
    )
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_deactivated_user_blocked_from_update(auth_client: AsyncClient):
    """PATCH /users/me must reject deactivated callers."""
    await auth_client.request(
        "DELETE", url="/users/me", json={"password": "password123"}
    )
    # Re-login so cookies are present again.
    await auth_client.post(
        "/auth/login",
        data={"username": "user_test@test.com", "password": "password123"},
    )

    response = await auth_client.patch("/users/me", json={"first_name": "Hacked"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reactivate_cancels_deletion(auth_client: AsyncClient):
    """Reactivate endpoint restores the account inside the grace window."""
    from sqlalchemy import select

    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    await auth_client.request(
        "DELETE", url="/users/me", json={"password": "password123"}
    )
    await auth_client.post(
        "/auth/login",
        data={"username": "user_test@test.com", "password": "password123"},
    )

    response = await auth_client.post("/users/me/reactivate")
    assert response.status_code == 200

    async with TestingSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "user_test@test.com")
        )
        user = result.scalars().one()
        assert user.is_active is True
        assert user.deactivated_at is None
        assert user.deletion_scheduled_at is None


@pytest.mark.asyncio
async def test_reactivate_on_active_account_returns_400(auth_client: AsyncClient):
    """Reactivating an account that isn't pending deletion must fail."""
    response = await auth_client.post("/users/me/reactivate")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_me_exposes_deletion_schedule(auth_client: AsyncClient):
    """GET /users/me must include deletion_scheduled_at for deactivated users."""
    await auth_client.request(
        "DELETE", url="/users/me", json={"password": "password123"}
    )
    await auth_client.post(
        "/auth/login",
        data={"username": "user_test@test.com", "password": "password123"},
    )

    response = await auth_client.get("/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False
    assert data["deactivated_at"] is not None
    assert data["deletion_scheduled_at"] is not None
