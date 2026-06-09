"""Account-lockout tests.

Exercised at the service/repository layer rather than over HTTP so the per-IP
``rate_limit_strict`` on ``/auth/login`` does not mask the lockout behaviour
(both share a threshold of 5, so a 6th HTTP call would 429 before we could
assert that a locked account rejects even a correct password).
"""

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import update

from app.core.config import settings
from app.core.messages.error_message import ErrorMessages
from app.models.user import User
from app.repositories.login_attempts import (
    clear_login_attempts,
    is_login_locked,
    register_failed_login,
)
from app.services.auth_service import authenticate
from app.tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_failed_logins_lock_after_threshold():
    """The threshold-crossing failure flips the account into a locked state."""
    email = "lock-repo@test.com"
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
        assert await register_failed_login(email) is False
    assert await is_login_locked(email) == 0

    assert await register_failed_login(email) is True
    assert await is_login_locked(email) > 0


@pytest.mark.asyncio
async def test_clear_login_attempts_unlocks():
    """A successful login clears the counter and any active lock."""
    email = "lock-clear@test.com"
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await register_failed_login(email)
    assert await is_login_locked(email) > 0

    await clear_login_attempts(email)
    assert await is_login_locked(email) == 0


@pytest.mark.asyncio
async def test_authenticate_locks_and_emails(client: AsyncClient, mock_email_send):
    """Wrong passwords lock the account, email the owner, then block valid logins."""
    email = "lockflow@test.com"
    password = "password123"

    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "F",
            "last_name": "L",
        },
    )
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == email).values(is_verified=True)
        )
        await session.commit()

    # Drop the registration verification email so later assertions are precise.
    mock_email_send.reset_mock()

    async with TestingSessionLocal() as session:
        # Wrong password below the threshold -> 401, no lock, no email.
        for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
            with pytest.raises(HTTPException) as exc:
                await authenticate(
                    request=None, session=session, email=email, password="wrong"
                )
            assert exc.value.status_code == 401
        mock_email_send.assert_not_called()

        # Threshold-crossing attempt -> 423 + exactly one lock notification.
        with pytest.raises(HTTPException) as exc:
            await authenticate(
                request=None, session=session, email=email, password="wrong"
            )
        assert exc.value.status_code == 423
        assert exc.value.detail == ErrorMessages.ACCOUNT_LOCKED
        assert exc.value.headers["Retry-After"]
        mock_email_send.assert_awaited_once()

        # A correct password is still rejected while the lock is active.
        with pytest.raises(HTTPException) as exc:
            await authenticate(
                request=None, session=session, email=email, password=password
            )
        assert exc.value.status_code == 423
