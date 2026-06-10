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
            "password": "Password123!",
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
async def test_register_rejects_weak_password(client: AsyncClient):
    # "password123" has no uppercase and no special character -> rejected.
    response = await client.post(
        "/auth/register",
        json={
            "email": "weakpw@test.com",
            "password": "password123",
            "first_name": "W",
            "last_name": "P",
        },
    )
    assert response.status_code == 422
    assert ErrorMessages.WEAK_PASSWORD in response.text


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    # Register first
    await client.post(
        "/auth/register",
        json={
            "email": "test2@test.com",
            "password": "Password123!",
            "first_name": "Test2",
            "last_name": "User2",
        },
    )

    # Login should fail because of unverified email
    response = await client.post(
        "/auth/login", data={"username": "test2@test.com", "password": "Password123!"}
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
            "password": "Password123!",
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
        "/auth/login", data={"username": "test3@test.com", "password": "Password123!"}
    )
    assert login_response.status_code == 200

    # Extract refresh token cookie
    refresh_cookie = login_response.cookies.get("refresh_token")
    assert refresh_cookie is not None

    # Test Refresh Endpoint
    client.cookies.set("refresh_token", refresh_cookie)
    refresh_response = await client.post("/auth/refresh")
    assert refresh_response.status_code == 200
    data = refresh_response.json()
    assert refresh_response.cookies.get("access_token") is not None
    assert data["message"] == SuccessMessages.LOGIN_SUCCESS

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
async def test_refresh_token_rotation(client: AsyncClient):
    from sqlalchemy import update

    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    email = "rotate@test.com"
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "first_name": "R",
            "last_name": "T",
        },
    )
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == email).values(is_verified=True)
        )
        await session.commit()

    login = await client.post(
        "/auth/login", data={"username": email, "password": "Password123!"}
    )
    assert login.status_code == 200
    r1 = login.cookies.get("refresh_token")
    assert r1 is not None

    # First refresh rotates the token: a new refresh cookie, different from r1.
    client.cookies.set("refresh_token", r1)
    first = await client.post("/auth/refresh")
    assert first.status_code == 200
    r2 = first.cookies.get("refresh_token")
    assert r2 is not None and r2 != r1

    # Replaying the old refresh token is rejected (revoked on rotation).
    client.cookies.set("refresh_token", r1)
    replay = await client.post("/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["error"] == ErrorMessages.INVALID_TOKEN

    # The rotated token works for a subsequent refresh.
    client.cookies.set("refresh_token", r2)
    second = await client.post("/auth/refresh")
    assert second.status_code == 200


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
            "password": "Password123!",
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
        "/auth/login", data={"username": email, "password": "Password123!"}
    )
    assert login_response.status_code == 200
    data = login_response.json()
    assert login_response.cookies.get("access_token") is not None
    assert data["message"] == SuccessMessages.LOGIN_SUCCESS


@pytest.mark.asyncio
async def test_forgot_and_reset_password_flow(client: AsyncClient):
    from app.core.security import create_password_reset_token

    email = "test5@test.com"
    old_password = "Password123!"
    new_password = "NewPassword456!"

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
    password = "Password123!"

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
        json={"token": reset_token, "new_password": "NewPassword123!"},
    )
    assert response.status_code == 200

    # 5. Reset Password Again with SAME token (Should Fail)
    response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "AnotherPassword123!"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.INVALID_TOKEN


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient):
    from sqlalchemy import update

    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal

    email = "test_change@test.com"
    old_password = "Password123!"
    new_password = "NewPassword456!"

    # 1. Register
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": old_password,
            "first_name": "Change",
            "last_name": "Tester",
        },
    )

    # 2. Verify handles login
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == email).values(is_verified=True)
        )
        await session.commit()

    # 3. Login to get access token cookie
    login_response = await client.post(
        "/auth/login", data={"username": email, "password": old_password}
    )
    assert login_response.status_code == 200
    assert login_response.cookies.get("access_token") is not None

    # 4. Test Change Password - Failure (Wrong current password)
    fail_response = await client.patch(
        "/auth/change-password",
        json={"current_password": "wrongpassword", "new_password": "NewPassword456!"},
    )
    assert fail_response.status_code == 400
    assert fail_response.json()["error"] == ErrorMessages.INVALID_CURRENT_PASSWORD

    # 5. Test Change Password - Success
    success_response = await client.patch(
        "/auth/change-password",
        json={"current_password": old_password, "new_password": new_password},
    )
    assert success_response.status_code == 200
    assert success_response.json()["success"] is True
    assert success_response.json()["message"] == SuccessMessages.PASSWORD_CHANGE_SUCCESS

    # 6. Verify Login works with NEW password
    new_login_response = await client.post(
        "/auth/login", data={"username": email, "password": new_password}
    )
    assert new_login_response.status_code == 200
    assert new_login_response.cookies.get("access_token") is not None

    # 7. Verify Login fails with OLD password
    old_login_response = await client.post(
        "/auth/login", data={"username": email, "password": old_password}
    )
    assert old_login_response.status_code == 401


@pytest.mark.asyncio
async def test_suspended_user_login_returns_account_suspended(client: AsyncClient):
    """A suspended account must be refused at login with the dedicated code."""
    from sqlalchemy import update

    from app.models.user import User
    from app.tests.conftest import TestingSessionLocal
    from app.utils import utc_now

    email = "suspended@test.com"
    password = "Password123!"
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "first_name": "Sus"},
    )

    async with TestingSessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.email == email)
            .values(is_verified=True, is_active=False, suspended_at=utc_now())
        )
        await session.commit()

    response = await client.post(
        "/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ACCOUNT_SUSPENDED
