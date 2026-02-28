import pytest
from httpx import AsyncClient


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

    # Login and get token
    response = await client.post(
        "/auth/login",
        data={
            "username": "user_test@test.com",
            "password": "password123",
        },
    )
    data = response.json()
    token = data["access_token"]

    # Set auth header
    client.headers["Authorization"] = f"Bearer {token}"
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
    assert data["first_name"] == "Updated"
    assert data["last_name"] == "Name"
    assert data["title"] == "Senior Tester"

    # Verify updates persisted
    response = await auth_client.get("/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "Updated"


@pytest.mark.asyncio
async def test_delete_user_me(auth_client: AsyncClient):
    # Attempt delete with wrong password
    response = await auth_client.request(
        "DELETE",
        url="/users/me",
        json={"password": "wrongpassword"},
    )
    assert response.status_code == 401

    # Attempt delete with correct password
    response = await auth_client.request(
        "DELETE",
        url="/users/me",
        json={"password": "password123"},
    )
    assert response.status_code == 200

    response = await auth_client.get("/users/me")
    assert response.status_code in (401, 403, 404)
