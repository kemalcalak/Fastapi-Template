"""End-to-end RBAC rule coverage: permission gating and superadmin guards.

Role transitions no longer happen on the users surface (admins are created and
deleted as accounts; the superadmin tier is managed root-only on the admins
surface), so this module focuses on per-permission gating and the protection
rules that stop a plain admin from acting on a superadmin.
"""

import pytest
from httpx import AsyncClient

from app.core.messages.error_message import ErrorMessages
from app.core.security import get_password_hash
from app.models.user import User
from app.repositories.admin.user import is_last_active_superadmin
from app.schemas.admin_permission import Permission
from app.schemas.user import SystemRole
from app.tests.admin.conftest import (
    get_user_id,
    grant_permissions,
    login,
    promote_to_admin,
    promote_to_superadmin,
    register_and_verify,
)
from app.tests.conftest import TestingSessionLocal


async def _make_admin(
    client: AsyncClient, email: str, permissions: list[Permission]
) -> None:
    """Register, promote to admin, grant the given permissions, and log in."""
    await register_and_verify(client, email)
    await promote_to_admin(email)
    if permissions:
        await grant_permissions(email, permissions)
    await login(client, email)


# --- Permission gating ------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_without_grant_is_forbidden(client: AsyncClient):
    """An admin holding no grants is rejected on a gated resource."""
    await _make_admin(client, "nogrants@test.com", [])
    response = await client.get("/admin/users")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.INSUFFICIENT_PERMISSIONS


@pytest.mark.asyncio
async def test_users_read_grant_allows_listing(client: AsyncClient):
    """The users:read grant unlocks exactly the read endpoints."""
    await _make_admin(client, "reader@test.com", [Permission.USERS_READ])
    response = await client.get("/admin/users")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_users_read_does_not_imply_write(client: AsyncClient):
    """A read-only admin cannot mutate a user."""
    await _make_admin(client, "readonly@test.com", [Permission.USERS_READ])
    await register_and_verify(client, "victim@test.com")
    target_id = await get_user_id("victim@test.com")

    response = await client.patch(
        f"/admin/users/{target_id}", json={"first_name": "Nope"}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.INSUFFICIENT_PERMISSIONS


# --- Role field is rejected on the users surface ----------------------------


@pytest.mark.asyncio
async def test_users_update_rejects_role_field(client: AsyncClient):
    """The users update payload no longer accepts a role field (422)."""
    await _make_admin(client, "writer@test.com", [Permission.USERS_WRITE])
    await register_and_verify(client, "rolesubject@test.com")
    target_id = await get_user_id("rolesubject@test.com")

    response = await client.patch(
        f"/admin/users/{target_id}", json={"role": SystemRole.ADMIN.value}
    )
    assert response.status_code == 422


# --- Superadmin protection (plain admin acting on a superadmin) --------------


@pytest.mark.asyncio
async def test_plain_admin_cannot_modify_superadmin(client: AsyncClient):
    """A plain admin cannot edit a superadmin even with users:write."""
    await _make_admin(client, "edituser@test.com", [Permission.USERS_WRITE])
    await register_and_verify(client, "thesuper@test.com")
    await promote_to_superadmin("thesuper@test.com")
    target_id = await get_user_id("thesuper@test.com")

    response = await client.patch(
        f"/admin/users/{target_id}", json={"first_name": "Hijack"}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_MODIFY_SUPERADMIN


@pytest.mark.asyncio
async def test_plain_admin_cannot_delete_superadmin(client: AsyncClient):
    """A plain admin cannot delete a superadmin even with users:delete."""
    await _make_admin(client, "deleter@test.com", [Permission.USERS_DELETE])
    await register_and_verify(client, "super-target@test.com")
    await promote_to_superadmin("super-target@test.com")
    target_id = await get_user_id("super-target@test.com")

    response = await client.delete(f"/admin/users/{target_id}")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_MODIFY_SUPERADMIN


@pytest.mark.asyncio
async def test_plain_admin_cannot_reset_superadmin_password(client: AsyncClient):
    """A plain admin cannot force-reset a superadmin's password."""
    await _make_admin(client, "resetter@test.com", [Permission.USERS_PASSWORD_RESET])
    await register_and_verify(client, "super-pw@test.com")
    await promote_to_superadmin("super-pw@test.com")
    target_id = await get_user_id("super-pw@test.com")

    response = await client.post(f"/admin/users/{target_id}/change-password")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_MODIFY_SUPERADMIN


# --- /users/me permission visibility ----------------------------------------


@pytest.mark.asyncio
async def test_me_hides_permissions_for_regular_user(client: AsyncClient):
    """A regular user never receives a permissions field."""
    await register_and_verify(client, "plain@test.com")
    await login(client, "plain@test.com")
    body = (await client.get("/users/me")).json()
    assert "permissions" not in body


@pytest.mark.asyncio
async def test_me_exposes_grants_for_admin(client: AsyncClient):
    """A plain admin sees exactly their granted permissions."""
    await _make_admin(client, "meadmin@test.com", [Permission.STATS_READ])
    body = (await client.get("/users/me")).json()
    assert body["permissions"] == [Permission.STATS_READ.value]


@pytest.mark.asyncio
async def test_me_hides_permissions_for_superadmin(superadmin_client: AsyncClient):
    """A superadmin gets no permissions list — their role implies everything."""
    body = (await superadmin_client.get("/users/me")).json()
    assert "permissions" not in body


# --- Repository guard -------------------------------------------------------


@pytest.mark.asyncio
async def test_is_last_active_superadmin_repository():
    """The repo flags the sole remaining active superadmin."""
    async with TestingSessionLocal() as session:
        only_super = User(
            email="solo-super@test.com",
            hashed_password=get_password_hash("Password123!"),
            role=SystemRole.SUPERADMIN.value,
            is_active=True,
            is_verified=True,
        )
        other_super = User(
            email="second-super@test.com",
            hashed_password=get_password_hash("Password123!"),
            role=SystemRole.SUPERADMIN.value,
            is_active=True,
            is_verified=True,
        )
        session.add(only_super)
        await session.commit()
        await session.refresh(only_super)

        assert await is_last_active_superadmin(session, only_super.id) is True

        session.add(other_super)
        await session.commit()

        assert await is_last_active_superadmin(session, only_super.id) is False
