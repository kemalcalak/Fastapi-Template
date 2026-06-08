"""Tests for the superadmin-only admin management endpoints (/admin/admins)."""

import pytest
from httpx import AsyncClient

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.schemas.admin_permission import Permission
from app.schemas.user import SystemRole
from app.tests.admin.conftest import (
    get_user_id,
    promote_to_admin,
    register_and_verify,
)


@pytest.mark.asyncio
async def test_permission_catalog_lists_all_keys(superadmin_client: AsyncClient):
    """The catalog exposes exactly the full permission enum."""
    response = await superadmin_client.get("/admin/admins/permissions")
    assert response.status_code == 200
    assert set(response.json()["permissions"]) == {p.value for p in Permission}


@pytest.mark.asyncio
async def test_list_admins_reports_superadmin_with_all_permissions(
    superadmin_client: AsyncClient,
):
    """The superadmin row surfaces as holding every permission."""
    response = await superadmin_client.get("/admin/admins")
    assert response.status_code == 200
    rows = response.json()["data"]
    superadmin_row = next(
        r for r in rows if r["role"] == SystemRole.SUPERADMIN.value
    )
    assert set(superadmin_row["permissions"]) == {p.value for p in Permission}


@pytest.mark.asyncio
async def test_promote_user_to_admin_with_permissions(superadmin_client: AsyncClient):
    """Promoting a user flips their role and seeds the requested grants."""
    await register_and_verify(superadmin_client, "promote@test.com")
    user_id = await get_user_id("promote@test.com")

    response = await superadmin_client.post(
        "/admin/admins",
        json={
            "user_id": user_id,
            "permissions": [Permission.USERS_READ.value, Permission.USERS_WRITE.value],
        },
    )
    assert response.status_code == 201, response.text
    admin = response.json()["admin"]
    assert admin["role"] == SystemRole.ADMIN.value
    assert set(admin["permissions"]) == {
        Permission.USERS_READ.value,
        Permission.USERS_WRITE.value,
    }
    assert response.json()["message"] == SuccessMessages.ADMIN_PROMOTED


@pytest.mark.asyncio
async def test_promote_already_admin_conflicts(superadmin_client: AsyncClient):
    """Promoting someone who is already an admin is a conflict."""
    await register_and_verify(superadmin_client, "already@test.com")
    await promote_to_admin("already@test.com")
    user_id = await get_user_id("already@test.com")

    response = await superadmin_client.post(
        "/admin/admins", json={"user_id": user_id, "permissions": []}
    )
    assert response.status_code == 409
    assert response.json()["error"] == ErrorMessages.ALREADY_AN_ADMIN


@pytest.mark.asyncio
async def test_set_admin_permissions_replaces_grants(superadmin_client: AsyncClient):
    """Setting permissions replaces the admin's grant set wholesale."""
    await register_and_verify(superadmin_client, "setperm@test.com")
    await promote_to_admin("setperm@test.com")
    user_id = await get_user_id("setperm@test.com")

    response = await superadmin_client.patch(
        f"/admin/admins/{user_id}/permissions",
        json={"permissions": [Permission.STATS_READ.value]},
    )
    assert response.status_code == 200
    assert response.json()["admin"]["permissions"] == [Permission.STATS_READ.value]


@pytest.mark.asyncio
async def test_set_permissions_on_non_admin_rejected(superadmin_client: AsyncClient):
    """Granting permissions to a plain user is rejected."""
    await register_and_verify(superadmin_client, "plainuser@test.com")
    user_id = await get_user_id("plainuser@test.com")

    response = await superadmin_client.patch(
        f"/admin/admins/{user_id}/permissions",
        json={"permissions": [Permission.STATS_READ.value]},
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.NOT_AN_ADMIN


@pytest.mark.asyncio
async def test_demote_admin_to_user(superadmin_client: AsyncClient):
    """Demotion reverts the role and drops the account from the admin list."""
    await register_and_verify(superadmin_client, "demoteme@test.com")
    await promote_to_admin("demoteme@test.com")
    user_id = await get_user_id("demoteme@test.com")

    response = await superadmin_client.delete(f"/admin/admins/{user_id}")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_DEMOTED

    listing = await superadmin_client.get("/admin/admins")
    assert user_id not in {row["id"] for row in listing.json()["data"]}


@pytest.mark.asyncio
async def test_demote_superadmin_rejected(superadmin_client: AsyncClient):
    """A superadmin's role is immutable, so demotion is refused."""
    superadmin_id = await get_user_id("superadmin@test.com")

    response = await superadmin_client.delete(f"/admin/admins/{superadmin_id}")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.SUPERADMIN_ROLE_IMMUTABLE


@pytest.mark.asyncio
async def test_admin_management_is_superadmin_only(admin_client: AsyncClient):
    """A plain admin — even with every permission — cannot manage admins."""
    response = await admin_client.get("/admin/admins")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ONLY_SUPERADMIN_ALLOWED
