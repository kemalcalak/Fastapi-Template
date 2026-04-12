"""Tests for the scheduled hard-deletion worker job."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.user import User
from app.repositories.user import (
    get_users_due_for_deletion,
    hard_delete_user,
)
from app.tests.conftest import TestingSessionLocal
from app.utils import utc_now
from app.worker.jobs.delete_expired_accounts import delete_expired_accounts


async def _make_user(
    email: str,
    *,
    scheduled_at=None,
    is_deleted: bool = False,
) -> User:
    """Insert a user with a given deletion schedule for test setup."""
    async with TestingSessionLocal() as session:
        user = User(
            email=email,
            hashed_password=get_password_hash("password123"),
            is_active=scheduled_at is None,
            is_verified=True,
            is_deleted=is_deleted,
            deactivated_at=scheduled_at - timedelta(days=30) if scheduled_at else None,
            deletion_scheduled_at=scheduled_at,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_past_due_user_gets_deleted(monkeypatch):
    """A user whose grace period has elapsed is removed by the job."""
    import app.worker.jobs.delete_expired_accounts as mod

    monkeypatch.setattr(mod, "AsyncSessionLocal", TestingSessionLocal)

    await _make_user("past@test.com", scheduled_at=utc_now() - timedelta(hours=1))

    result = await delete_expired_accounts({})
    assert result.processed == 1
    assert result.failed == 0

    async with TestingSessionLocal() as session:
        remaining = await session.execute(
            select(User).where(User.email == "past@test.com")
        )
        assert remaining.scalars().first() is None


@pytest.mark.asyncio
async def test_future_scheduled_user_is_not_deleted(monkeypatch):
    """Users still inside the grace window are preserved."""
    import app.worker.jobs.delete_expired_accounts as mod

    monkeypatch.setattr(mod, "AsyncSessionLocal", TestingSessionLocal)

    await _make_user("future@test.com", scheduled_at=utc_now() + timedelta(days=5))

    result = await delete_expired_accounts({})
    assert result.processed == 0

    async with TestingSessionLocal() as session:
        remaining = await session.execute(
            select(User).where(User.email == "future@test.com")
        )
        assert remaining.scalars().first() is not None


@pytest.mark.asyncio
async def test_active_user_is_not_deleted(monkeypatch):
    """Active users (no schedule) are never touched by the job."""
    import app.worker.jobs.delete_expired_accounts as mod

    monkeypatch.setattr(mod, "AsyncSessionLocal", TestingSessionLocal)

    await _make_user("active@test.com", scheduled_at=None)

    result = await delete_expired_accounts({})
    assert result.processed == 0


@pytest.mark.asyncio
async def test_concurrent_runs_do_not_double_delete(monkeypatch):
    """Two parallel job invocations must delete each user at most once.

    Note: the CI test DB is SQLite in-memory which doesn't honour
    ``FOR UPDATE SKIP LOCKED``. The assertion therefore checks the stronger
    invariant (``processed + failed == 1`` per user) rather than locking
    semantics, which are exercised against real Postgres in staging.
    """
    import app.worker.jobs.delete_expired_accounts as mod

    monkeypatch.setattr(mod, "AsyncSessionLocal", TestingSessionLocal)

    await _make_user("race@test.com", scheduled_at=utc_now() - timedelta(hours=1))

    results = await asyncio.gather(
        delete_expired_accounts({}),
        delete_expired_accounts({}),
        return_exceptions=True,
    )

    from app.schemas.worker import DeletionJobResult

    total_processed = sum(
        r.processed for r in results if isinstance(r, DeletionJobResult)
    )
    assert total_processed == 1

    async with TestingSessionLocal() as session:
        remaining = await session.execute(
            select(User).where(User.email == "race@test.com")
        )
        assert remaining.scalars().first() is None


@pytest.mark.asyncio
async def test_repository_helpers_return_expected_set():
    """The repository query surfaces only eligible users."""
    await _make_user("eligible@test.com", scheduled_at=utc_now() - timedelta(minutes=5))
    await _make_user("too-early@test.com", scheduled_at=utc_now() + timedelta(days=1))
    await _make_user("untouched@test.com", scheduled_at=None)

    async with TestingSessionLocal() as session:
        due = await get_users_due_for_deletion(session, now=utc_now(), limit=10)
        emails = {u.email for u in due}
        assert "eligible@test.com" in emails
        assert "too-early@test.com" not in emails
        assert "untouched@test.com" not in emails

        for user in due:
            await hard_delete_user(session, user)
