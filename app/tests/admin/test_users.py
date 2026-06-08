"""End-to-end tests for /admin/users endpoints.

Covers listing, detail, update, suspend/unsuspend, delete, admin password
rotation, self-protection, and the last-admin repository guard.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.user import User
from app.schemas.user import SystemRole
from app.tests.admin.conftest import (
    get_user_id,
    grant_all_permissions,
    login,
    promote_to_admin,
    register_and_verify,
)
from app.tests.conftest import TestingSessionLocal

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


async def _upload_png(client: AsyncClient, name: str = "a.png") -> str:
    """Upload a PNG via the client and return the created file id."""
    response = await client.post(
        "/upload", files={"file": (name, PNG_BYTES, "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


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
async def test_admin_user_views_include_avatar(admin_client: AsyncClient):
    """A user's avatar surfaces in both the admin list and detail views."""
    png = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    file_id = (
        await admin_client.post("/upload", files={"file": ("a.png", png, "image/png")})
    ).json()["id"]
    await admin_client.patch("/users/me", json={"avatar_file_id": file_id})

    listing = await admin_client.get("/admin/users?search=admin@test.com")
    admin_row = next(
        u for u in listing.json()["data"] if u["email"] == "admin@test.com"
    )
    assert admin_row["avatar_file"]["id"] == file_id
    assert admin_row["avatar_file"]["url"] == "https://cdn.test/img.png"

    admin_id = await get_user_id("admin@test.com")
    detail = await admin_client.get(f"/admin/users/{admin_id}")
    assert detail.json()["avatar_file"]["id"] == file_id

    await register_and_verify(admin_client, "noavatar@test.com")
    other_id = await get_user_id("noavatar@test.com")
    other = await admin_client.get(f"/admin/users/{other_id}")
    assert other.json()["avatar_file"] is None


@pytest.mark.asyncio
async def test_regular_user_avatar_visible_to_admin(client: AsyncClient):
    """An avatar set by a regular user surfaces in the admin list and detail."""
    png = b"\x89PNG\r\n\x1a\nfake-image-bytes"

    # A regular user uploads and attaches their own avatar.
    await register_and_verify(client, "member@test.com")
    await login(client, "member@test.com")
    file_id = (
        await client.post("/upload", files={"file": ("a.png", png, "image/png")})
    ).json()["id"]
    await client.patch("/users/me", json={"avatar_file_id": file_id})
    member_id = await get_user_id("member@test.com")

    # An admin then views the user list and detail.
    await register_and_verify(client, "admin@test.com")
    await promote_to_admin("admin@test.com")
    await grant_all_permissions("admin@test.com")
    await login(client, "admin@test.com")

    listing = await client.get("/admin/users?search=member@test.com")
    row = next(u for u in listing.json()["data"] if u["email"] == "member@test.com")
    assert row["avatar_file"]["id"] == file_id
    assert row["avatar_file"]["url"] == "https://cdn.test/img.png"

    detail = await client.get(f"/admin/users/{member_id}")
    assert detail.json()["avatar_file"]["id"] == file_id


@pytest.mark.asyncio
async def test_admin_sets_user_avatar(admin_client: AsyncClient):
    """An admin can attach a file they uploaded as another user's avatar."""
    await register_and_verify(admin_client, "target@test.com")
    target_id = await get_user_id("target@test.com")
    file_id = await _upload_png(admin_client)

    response = await admin_client.patch(
        f"/admin/users/{target_id}", json={"avatar_file_id": file_id}
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["avatar_file"]["id"] == file_id


@pytest.mark.asyncio
async def test_admin_replacing_avatar_deletes_old_file(admin_client: AsyncClient):
    """Replacing a user's avatar purges the previous file (Cloudinary + DB)."""
    await register_and_verify(admin_client, "target@test.com")
    target_id = await get_user_id("target@test.com")

    first_id = await _upload_png(admin_client, "first.png")
    await admin_client.patch(
        f"/admin/users/{target_id}", json={"avatar_file_id": first_id}
    )

    second_id = await _upload_png(admin_client, "second.png")
    response = await admin_client.patch(
        f"/admin/users/{target_id}", json={"avatar_file_id": second_id}
    )
    assert response.json()["user"]["avatar_file"]["id"] == second_id

    # The replaced file no longer exists.
    gone = await admin_client.get(f"/admin/files/{first_id}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_admin_clearing_avatar_deletes_file(admin_client: AsyncClient):
    """Clearing the avatar (null) drops the reference and deletes the file."""
    await register_and_verify(admin_client, "target@test.com")
    target_id = await get_user_id("target@test.com")

    file_id = await _upload_png(admin_client)
    await admin_client.patch(
        f"/admin/users/{target_id}", json={"avatar_file_id": file_id}
    )

    response = await admin_client.patch(
        f"/admin/users/{target_id}", json={"avatar_file_id": None}
    )
    assert response.status_code == 200
    assert response.json()["user"]["avatar_file"] is None

    gone = await admin_client.get(f"/admin/files/{file_id}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_admin_set_avatar_missing_file_returns_404(admin_client: AsyncClient):
    """Assigning a non-existent file id as an avatar returns 404."""
    await register_and_verify(admin_client, "target@test.com")
    target_id = await get_user_id("target@test.com")

    response = await admin_client.patch(
        f"/admin/users/{target_id}", json={"avatar_file_id": str(uuid.uuid4())}
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
async def test_demote_non_last_admin_succeeds(superadmin_client: AsyncClient):
    """A superadmin can demote an admin while another active admin still remains.

    Only superadmins may change an admin's role, so the actor is a superadmin;
    two admins are seeded so the demoted one is not the last.
    """
    await register_and_verify(superadmin_client, "admin-a@test.com")
    await promote_to_admin("admin-a@test.com")
    await register_and_verify(superadmin_client, "admin-b@test.com")
    await promote_to_admin("admin-b@test.com")
    admin_b_id = await get_user_id("admin-b@test.com")

    response = await superadmin_client.patch(
        f"/admin/users/{admin_b_id}",
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
async def test_change_password_rotates_hash_and_notifies(
    admin_client: AsyncClient, mock_email_send
):
    """Admin change-password rotates the hash to an unknown value and notifies the user.

    The new password must never appear in the response, the email must be
    link-free, and an activity row must be written so the rotation is auditable.
    """
    from app.models.user_activity import UserActivity

    await register_and_verify(admin_client, "rotateme@test.com")
    user_id = await get_user_id("rotateme@test.com")

    async with TestingSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "rotateme@test.com")
        )
        original_hash = result.scalars().one().hashed_password

    mock_email_send.reset_mock()

    response = await admin_client.post(f"/admin/users/{user_id}/change-password")
    assert response.status_code == 200

    body = response.json()
    assert body["message"] == SuccessMessages.ADMIN_PASSWORD_CHANGED
    # The new password must never leak to the caller, under any field name.
    for leak_key in ("password", "new_password", "temporary_password"):
        assert leak_key not in body

    # Email reached the target — and is deliberately link-free.
    mock_email_send.assert_awaited_once()
    call_kwargs = mock_email_send.await_args.kwargs
    assert call_kwargs["to"] == "rotateme@test.com"
    assert "href=" not in call_kwargs["body"]
    assert "http" not in call_kwargs["plain_text"].lower()

    # Hash was rotated; the old hash no longer matches.
    async with TestingSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "rotateme@test.com")
        )
        new_hash = result.scalars().one().hashed_password
    assert new_hash != original_hash

    # Audit trail recorded the rotation.
    async with TestingSessionLocal() as session:
        result = await session.execute(select(UserActivity))
        actions = [
            row.details.get("action") for row in result.scalars().all() if row.details
        ]
    assert "admin_reset_user_password" in actions
