import pytest
from httpx import AsyncClient

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages


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
    assert data["success"] is True
    assert data["message"] == SuccessMessages.REGISTER_SUCCESS


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    # Register first
    await client.post(
        "/auth/register",
        json={
            "email": "test2@test.com",
            "password": "password123",
            "first_name": "Test2",
            "last_name": "User2",
        },
    )

    # Login should fail because of unverified email
    response = await client.post(
        "/auth/login", data={"username": "test2@test.com", "password": "password123"}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.EMAIL_NOT_VERIFIED

    # We need to manually verify them in DB or bypass this.
    # We will test the `/verify-email` endpoint below to verify this properly.


@pytest.mark.asyncio
async def test_refresh_token_and_logout(client: AsyncClient):
    from sqlalchemy import update

    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    # Register
    await client.post(
        "/auth/register",
        json={
            "email": "test3@test.com",
            "password": "password123",
            "first_name": "Test3",
            "last_name": "User3",
        },
    )

    # Verify the user directly in DB to test the rest of the flow
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == "test3@test.com").values(is_verified=True)
        )
        await session.commit()

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


@pytest.mark.asyncio
async def test_verify_email_flow(client: AsyncClient):
    from sqlalchemy import select

    from app.core.security import generate_new_account_token
    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    email = "test4@test.com"

    # Register
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
            "first_name": "Test4",
            "last_name": "User4",
        },
    )

    # Validate db state before verification
    async with TestingSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        assert user is not None
        assert not user.is_verified

    # Generate token
    token = generate_new_account_token(email)

    # Verify Email
    response = await client.post("/auth/verify-email", json={"token": token})
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Validate db state after verification
    async with TestingSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        assert user.is_verified

    # Login should now succeed
    login_response = await client.post(
        "/auth/login", data={"username": email, "password": "password123"}
    )
    assert login_response.status_code == 200
    assert "access_token" in login_response.json()


@pytest.mark.asyncio
async def test_forgot_and_reset_password_flow(client: AsyncClient):
    from app.core.security import create_password_reset_token

    email = "test5@test.com"
    old_password = "password123"
    new_password = "newPassword456"

    # Register
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": old_password,
            "first_name": "Test5",
            "last_name": "User5",
        },
    )

    # Call Forgot Password
    forgot_response = await client.post("/auth/forgot-password", json={"email": email})
    assert forgot_response.status_code == 200
    assert forgot_response.json()["success"] is True

    # Verify that requesting for an unknown email also works (no email leaking)
    unknown_forgot_response = await client.post(
        "/auth/forgot-password", json={"email": "unknown@test.com"}
    )
    assert unknown_forgot_response.status_code == 200

    # Reset Password
    reset_token = create_password_reset_token(email)
    reset_response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": new_password},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["success"] is True

    # Fix is_verified so we can login
    from sqlalchemy import update

    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == email).values(is_verified=True)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_token_reuse_protection(client: AsyncClient):
    from app.core.security import (
        create_password_reset_token,
        generate_new_account_token,
    )

    email = "test_reuse@test.com"
    password = "password123"

    # 1. Register
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Reuse",
            "last_name": "Tester",
        },
    )

    # 2. Verify Email Once
    token = generate_new_account_token(email)
    response = await client.post("/auth/verify-email", json={"token": token})
    assert response.status_code == 200

    # 3. Verify Email Again with SAME token (Should Fail)
    response = await client.post("/auth/verify-email", json={"token": token})
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.INVALID_TOKEN

    # 4. Reset Password Once
    reset_token = create_password_reset_token(email)
    response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "newPassword123"},
    )
    assert response.status_code == 200

    # 5. Reset Password Again with SAME token (Should Fail)
    response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "anotherPassword123"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.INVALID_TOKEN
