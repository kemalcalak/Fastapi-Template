"""End-to-end RBAC rule coverage: permission gating, role rules, superadmin guards.

The conditional ``support:update`` permission rides the same
``require_permissions`` factory as ``users:role`` (covered here), so the users
domain exercises that mechanism without standing up a full ticket flow.
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


# --- Conditional permission: users:role ------------------------------------


@pytest.mark.asyncio
async def test_users_write_without_role_cannot_change_role(client: AsyncClient):
    """users:write alone cannot touch the role field — that needs users:role."""
    await _make_admin(client, "writer@test.com", [Permission.USERS_WRITE])
    await register_and_verify(client, "promote-me@test.com")
    target_id = await get_user_id("promote-me@test.com")

    response = await client.patch(
        f"/admin/users/{target_id}", json={"role": SystemRole.ADMIN.value}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.INSUFFICIENT_PERMISSIONS


@pytest.mark.asyncio
async def test_users_role_allows_promoting_a_user_to_admin(client: AsyncClient):
    """users:write + users:role lets an admin promote a plain user to admin."""
    await _make_admin(
        client, "maker@test.com", [Permission.USERS_WRITE, Permission.USERS_ROLE]
    )
    await register_and_verify(client, "rookie@test.com")
    target_id = await get_user_id("rookie@test.com")

    response = await client.patch(
        f"/admin/users/{target_id}", json={"role": SystemRole.ADMIN.value}
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == SystemRole.ADMIN.value


@pytest.mark.asyncio
async def test_admin_cannot_change_another_admins_role(client: AsyncClient):
    """No admin may change another admin's role — only superadmins can."""
    await _make_admin(
        client, "boss@test.com", [Permission.USERS_WRITE, Permission.USERS_ROLE]
    )
    await register_and_verify(client, "peer-admin@test.com")
    await promote_to_admin("peer-admin@test.com")
    target_id = await get_user_id("peer-admin@test.com")

    response = await client.patch(
        f"/admin/users/{target_id}", json={"role": SystemRole.USER.value}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_CHANGE_ADMIN_ROLE


@pytest.mark.asyncio
async def test_admin_cannot_grant_superadmin_role(client: AsyncClient):
    """Granting the superadmin role is superadmin-only."""
    await _make_admin(
        client, "wannabe@test.com", [Permission.USERS_WRITE, Permission.USERS_ROLE]
    )
    await register_and_verify(client, "elevate@test.com")
    target_id = await get_user_id("elevate@test.com")

    response = await client.patch(
        f"/admin/users/{target_id}", json={"role": SystemRole.SUPERADMIN.value}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ONLY_SUPERADMIN_ALLOWED


@pytest.mark.asyncio
async def test_superadmin_role_is_immutable(superadmin_client: AsyncClient):
    """Not even a superadmin may change another superadmin's role."""
    await register_and_verify(superadmin_client, "peer-super@test.com")
    await promote_to_superadmin("peer-super@test.com")
    target_id = await get_user_id("peer-super@test.com")

    response = await superadmin_client.patch(
        f"/admin/users/{target_id}", json={"role": SystemRole.USER.value}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.SUPERADMIN_ROLE_IMMUTABLE


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
            hashed_password=get_password_hash("password123"),
            role=SystemRole.SUPERADMIN.value,
            is_active=True,
            is_verified=True,
        )
        other_super = User(
            email="second-super@test.com",
            hashed_password=get_password_hash("password123"),
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
