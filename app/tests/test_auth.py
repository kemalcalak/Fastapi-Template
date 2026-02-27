import pytest
from httpx import AsyncClient

from app.core.messages.error_message import ErrorMessages


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={
            "email": "test@test.com",
            "password": "password123",
            "first_name": "Test",
            "last_name": "User",
            "title": "Tester",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@test.com"
    assert "id" in data


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    # Register first (to ensure user exists in the DB for the session)
    await client.post(
        "/auth/register",
        json={
            "email": "test2@test.com",
            "password": "password123",
            "first_name": "Test2",
            "last_name": "User2",
        },
    )

    # Now try to login using form data
    response = await client.post(
        "/auth/login", data={"username": "test2@test.com", "password": "password123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "refresh_token" in response.cookies


@pytest.mark.asyncio
async def test_refresh_token_and_logout(client: AsyncClient):
    # Register and login
    await client.post(
        "/auth/register",
        json={
            "email": "test3@test.com",
            "password": "password123",
            "first_name": "Test3",
            "last_name": "User3",
        },
    )
    login_response = await client.post(
        "/auth/login", data={"username": "test3@test.com", "password": "password123"}
    )
    assert login_response.status_code == 200
    
    # Extract refresh token cookie
    refresh_cookie = login_response.cookies.get("refresh_token")
    assert refresh_cookie is not None

    # Test Refresh Endpoint
    client.cookies.set("refresh_token", refresh_cookie)
    refresh_response = await client.post("/auth/refresh")
    assert refresh_response.status_code == 200
    assert "access_token" in refresh_response.json()

    # Test Logout Endpoint
    logout_response = await client.post("/auth/logout")
    assert logout_response.status_code == 200
    
    # Refresh should now fail because token is blacklisted
    # Since cookies are cleared in logout, we need to explicitly set it back to the old one to test blacklist
    client.cookies.set("refresh_token", refresh_cookie)
    failed_refresh_response = await client.post("/auth/refresh")
    assert failed_refresh_response.status_code == 401
    assert failed_refresh_response.json()["error"] == ErrorMessages.INVALID_TOKEN
