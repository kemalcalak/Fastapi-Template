import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={
            "email": "test@test.com",
            "password": "password123",
            "first_name": "Test",
            "last_name": "User",
            "title": "Tester"
        }
    )
    assert response.status_code == 200
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
            "last_name": "User2"
        }
    )
    
    # Now try to login using form data
    response = await client.post(
        "/auth/login",
        data={
            "username": "test2@test.com",
            "password": "password123"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
