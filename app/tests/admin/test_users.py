"""End-to-end tests for /admin/users endpoints.

Covers listing, detail, update, suspend/unsuspend, delete, password reset,
self-protection, and the last-admin repository guard.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.user import User
from app.schemas.user import SystemRole
from app.tests.admin.conftest import (
    get_user_id,
    promote_to_admin,
    register_and_verify,
)
from app.tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_list_users_requires_admin(regular_client: AsyncClient):
    """A non-admin must receive 403 from any /admin endpoint."""
    response = await regular_client.get("/admin/users")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_without_auth_returns_401(client: AsyncClient):
    """An unauthenticated caller must receive 401, not 403."""
    response = await client.get("/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_users_paginates_and_filters(admin_client: AsyncClient):
    """Listing returns the admin plus seeded users and honours filters."""
    await register_and_verify(admin_client, "alice@test.com")
    await register_and_verify(admin_client, "bob@test.com")

    response = await admin_client.get("/admin/users?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 3
    emails = [u["email"] for u in body["data"]]
    assert "alice@test.com" in emails

    response = await admin_client.get("/admin/users?search=alice")
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["email"] == "alice@test.com"

    response = await admin_client.get(f"/admin/users?role={SystemRole.ADMIN.value}")
    body = response.json()
    assert all(u["role"] == SystemRole.ADMIN.value for u in body["data"])


@pytest.mark.asyncio
async def test_get_user_returns_detail(admin_client: AsyncClient):
    """GET /admin/users/{id} returns the full admin view."""
    await register_and_verify(admin_client, "detail@test.com")
    user_id = await get_user_id("detail@test.com")

    response = await admin_client.get(f"/admin/users/{user_id}")
    assert response.status_code == 200
    assert response.json()["email"] == "detail@test.com"


@pytest.mark.asyncio
async def test_get_user_not_found(admin_client: AsyncClient):
    """Unknown user id must return 404 with the shared error code."""
    response = await admin_client.get(
        "/admin/users/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_user_changes_profile(admin_client: AsyncClient):
    """PATCH updates the profile fields and returns the new detail."""
    await register_and_verify(admin_client, "edit@test.com")
    user_id = await get_user_id("edit@test.com")

    response = await admin_client.patch(
        f"/admin/users/{user_id}",
        json={"first_name": "Edited", "title": "Staff"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == SuccessMessages.ADMIN_USER_UPDATED
    assert body["user"]["first_name"] == "Edited"
    assert body["user"]["title"] == "Staff"


@pytest.mark.asyncio
async def test_admin_cannot_change_user_email(admin_client: AsyncClient):
    """An ``email`` key in the admin update payload is rejected by the schema.

    Identity (login + recovery channel) is owned by the user; an admin must
    never be able to rewrite it. ``extra=forbid`` on AdminUserUpdate turns the
    field into a 422 so it can't be dropped silently.
    """
    await register_and_verify(admin_client, "identity@test.com")
    user_id = await get_user_id("identity@test.com")

    response = await admin_client.patch(
        f"/admin/users/{user_id}",
        json={"email": "stolen@test.com"},
    )
    assert response.status_code == 422

    async with TestingSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "identity@test.com")
        )
        assert result.scalars().one_or_none() is not None  # Email unchanged
        result = await session.execute(
            select(User).where(User.email == "stolen@test.com")
        )
        assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_admin_cannot_demote_self(admin_client: AsyncClient):
    """An admin must not be able to change their own role."""
    admin_id = await get_user_id("admin@test.com")

    response = await admin_client.patch(
        f"/admin/users/{admin_id}",
        json={"role": SystemRole.USER.value},
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_MODIFY_SELF


@pytest.mark.asyncio
async def test_demote_non_last_admin_succeeds(admin_client: AsyncClient):
    """A second admin can be demoted when another active admin still remains."""
    await register_and_verify(admin_client, "second-admin@test.com")
    await promote_to_admin("second-admin@test.com")
    second_admin_id = await get_user_id("second-admin@test.com")

    response = await admin_client.patch(
        f"/admin/users/{second_admin_id}",
        json={"role": SystemRole.USER.value},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == SystemRole.USER.value


@pytest.mark.asyncio
async def test_is_last_active_admin_repository():
    """Repository guard correctly flags the sole remaining active admin.

    Exercised at the repo layer because the HTTP flow always has an active
    admin caller, so the route-level guard is defence-in-depth for states
    the dependency chain rejects.
    """
    from app.core.security import get_password_hash
    from app.repositories.admin.user import is_last_active_admin

    async with TestingSessionLocal() as session:
        only_admin = User(
            email="solo-admin@test.com",
            hashed_password=get_password_hash("password123"),
            role=SystemRole.ADMIN.value,
            is_active=True,
            is_verified=True,
        )
        inactive_admin = User(
            email="inactive-admin@test.com",
            hashed_password=get_password_hash("password123"),
            role=SystemRole.ADMIN.value,
            is_active=False,
            is_verified=True,
        )
        regular = User(
            email="plain@test.com",
            hashed_password=get_password_hash("password123"),
            role=SystemRole.USER.value,
            is_active=True,
            is_verified=True,
        )
        session.add_all([only_admin, inactive_admin, regular])
        await session.commit()
        await session.refresh(only_admin)

        assert await is_last_active_admin(session, only_admin.id) is True

        second_admin = User(
            email="second-admin@test.com",
            hashed_password=get_password_hash("password123"),
            role=SystemRole.ADMIN.value,
            is_active=True,
            is_verified=True,
        )
        session.add(second_admin)
        await session.commit()

        assert await is_last_active_admin(session, only_admin.id) is False


@pytest.mark.asyncio
async def test_suspend_and_unsuspend_user(admin_client: AsyncClient):
    """Suspend then unsuspend a user; suspended rows never get a deletion schedule."""
    await register_and_verify(admin_client, "toggle@test.com")
    user_id = await get_user_id("toggle@test.com")

    response = await admin_client.post(f"/admin/users/{user_id}/suspend")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_USER_SUSPENDED

    async with TestingSessionLocal() as session:
        user = (
            (await session.execute(select(User).where(User.email == "toggle@test.com")))
            .scalars()
            .one()
        )
        assert user.is_active is False
        assert user.suspended_at is not None
        # Critical invariant: admin suspension must NOT schedule deletion.
        assert user.deletion_scheduled_at is None

    response = await admin_client.post(f"/admin/users/{user_id}/unsuspend")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_USER_UNSUSPENDED

    async with TestingSessionLocal() as session:
        user = (
            (await session.execute(select(User).where(User.email == "toggle@test.com")))
            .scalars()
            .one()
        )
        assert user.is_active is True
        assert user.suspended_at is None


@pytest.mark.asyncio
async def test_admin_cannot_suspend_self(admin_client: AsyncClient):
    """Self-suspension must be blocked for admins."""
    admin_id = await get_user_id("admin@test.com")
    response = await admin_client.post(f"/admin/users/{admin_id}/suspend")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_MODIFY_SELF


@pytest.mark.asyncio
async def test_admin_cannot_suspend_already_suspended(admin_client: AsyncClient):
    """Re-suspending a suspended user returns the dedicated error code."""
    await register_and_verify(admin_client, "already-suspended@test.com")
    user_id = await get_user_id("already-suspended@test.com")

    first = await admin_client.post(f"/admin/users/{user_id}/suspend")
    assert first.status_code == 200

    second = await admin_client.post(f"/admin/users/{user_id}/suspend")
    assert second.status_code == 400
    assert second.json()["error"] == ErrorMessages.ACCOUNT_ALREADY_SUSPENDED


@pytest.mark.asyncio
async def test_admin_cannot_unsuspend_not_suspended(admin_client: AsyncClient):
    """Unsuspending an active user returns the dedicated error code."""
    await register_and_verify(admin_client, "never-suspended@test.com")
    user_id = await get_user_id("never-suspended@test.com")

    response = await admin_client.post(f"/admin/users/{user_id}/unsuspend")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.ACCOUNT_NOT_SUSPENDED


@pytest.mark.asyncio
async def test_delete_user_removes_row(admin_client: AsyncClient):
    """DELETE permanently removes the target user."""
    await register_and_verify(admin_client, "bye@test.com")
    user_id = await get_user_id("bye@test.com")

    response = await admin_client.delete(f"/admin/users/{user_id}")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_USER_DELETED

    async with TestingSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "bye@test.com"))
        assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(admin_client: AsyncClient):
    """Self-delete must be rejected with the dedicated error code."""
    admin_id = await get_user_id("admin@test.com")
    response = await admin_client.delete(f"/admin/users/{admin_id}")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_DELETE_SELF


@pytest.mark.asyncio
async def test_delete_non_last_admin_succeeds(admin_client: AsyncClient):
    """A second admin can be deleted while another active admin remains."""
    await register_and_verify(admin_client, "other-admin@test.com")
    await promote_to_admin("other-admin@test.com")
    other_admin_id = await get_user_id("other-admin@test.com")

    response = await admin_client.delete(f"/admin/users/{other_admin_id}")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_USER_DELETED

    async with TestingSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "other-admin@test.com")
        )
        assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_reset_password_sends_email(admin_client: AsyncClient, mock_email_send):
    """Reset endpoint must hit the email service with the target user's address."""
    await register_and_verify(admin_client, "resetme@test.com")
    user_id = await get_user_id("resetme@test.com")

    mock_email_send.reset_mock()

    response = await admin_client.post(f"/admin/users/{user_id}/reset-password")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_PASSWORD_RESET_SENT

    mock_email_send.assert_awaited_once()
    call_kwargs = mock_email_send.await_args.kwargs
    assert call_kwargs["to"] == "resetme@test.com"
