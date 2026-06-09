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
    promote_to_superadmin,
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
    superadmin_row = next(r for r in rows if r["role"] == SystemRole.SUPERADMIN.value)
    assert set(superadmin_row["permissions"]) == {p.value for p in Permission}
    assert superadmin_row["is_root_superadmin"] is True


# --- Create admin -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_admin_account_with_permissions(superadmin_client: AsyncClient):
    """Creating an admin provisions a new account and seeds the grants."""
    response = await superadmin_client.post(
        "/admin/admins",
        json={
            "email": "newadmin@test.com",
            "first_name": "New",
            "last_name": "Admin",
            "password": "password123",
            "permissions": [Permission.USERS_READ.value, Permission.USERS_WRITE.value],
        },
    )
    assert response.status_code == 201, response.text
    admin = response.json()["admin"]
    assert admin["email"] == "newadmin@test.com"
    assert admin["role"] == SystemRole.ADMIN.value
    assert admin["is_root_superadmin"] is False
    assert set(admin["permissions"]) == {
        Permission.USERS_READ.value,
        Permission.USERS_WRITE.value,
    }
    assert response.json()["message"] == SuccessMessages.ADMIN_CREATED


@pytest.mark.asyncio
async def test_create_admin_duplicate_email_conflicts(superadmin_client: AsyncClient):
    """Creating an admin with an existing email is a conflict."""
    await register_and_verify(superadmin_client, "taken@test.com")

    response = await superadmin_client.post(
        "/admin/admins",
        json={"email": "taken@test.com", "password": "password123", "permissions": []},
    )
    assert response.status_code == 409
    assert response.json()["error"] == ErrorMessages.EMAIL_ALREADY_EXISTS


# --- Set permissions --------------------------------------------------------


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


# --- Delete admin account ---------------------------------------------------


@pytest.mark.asyncio
async def test_delete_admin_account(superadmin_client: AsyncClient):
    """Deleting an admin removes the account from the admin list."""
    # Seed a second admin so the deleted one is not the last active admin.
    await register_and_verify(superadmin_client, "keepme@test.com")
    await promote_to_admin("keepme@test.com")
    await register_and_verify(superadmin_client, "deleteme@test.com")
    await promote_to_admin("deleteme@test.com")
    user_id = await get_user_id("deleteme@test.com")

    response = await superadmin_client.delete(f"/admin/admins/{user_id}")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_ACCOUNT_DELETED

    listing = await superadmin_client.get("/admin/admins")
    assert user_id not in {row["id"] for row in listing.json()["data"]}


@pytest.mark.asyncio
async def test_delete_last_admin_rejected(superadmin_client: AsyncClient):
    """The last active admin cannot be deleted (mirrors the /admin/users guard)."""
    await register_and_verify(superadmin_client, "solo@test.com")
    await promote_to_admin("solo@test.com")
    user_id = await get_user_id("solo@test.com")

    response = await superadmin_client.delete(f"/admin/admins/{user_id}")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.ADMIN_CANNOT_DELETE_LAST_ADMIN


@pytest.mark.asyncio
async def test_delete_non_admin_rejected(superadmin_client: AsyncClient):
    """Deleting a plain user via the admins endpoint is rejected."""
    await register_and_verify(superadmin_client, "notadmin@test.com")
    user_id = await get_user_id("notadmin@test.com")

    response = await superadmin_client.delete(f"/admin/admins/{user_id}")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.NOT_AN_ADMIN


@pytest.mark.asyncio
async def test_delete_superadmin_rejected(superadmin_client: AsyncClient):
    """A superadmin cannot be deleted here — it must be demoted to admin first."""
    superadmin_id = await get_user_id("superadmin@test.com")

    response = await superadmin_client.delete(f"/admin/admins/{superadmin_id}")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.NOT_AN_ADMIN


# --- Promote admin -> superadmin (root only) --------------------------------


@pytest.mark.asyncio
async def test_root_promotes_admin_to_superadmin(superadmin_client: AsyncClient):
    """The root superadmin can promote a plain admin to superadmin."""
    await register_and_verify(superadmin_client, "rising@test.com")
    await promote_to_admin("rising@test.com")
    user_id = await get_user_id("rising@test.com")

    response = await superadmin_client.post(f"/admin/admins/{user_id}/promote")
    assert response.status_code == 200, response.text
    admin = response.json()["admin"]
    assert admin["role"] == SystemRole.SUPERADMIN.value
    assert set(admin["permissions"]) == {p.value for p in Permission}
    assert response.json()["message"] == SuccessMessages.SUPERADMIN_PROMOTED


@pytest.mark.asyncio
async def test_promote_non_admin_rejected(superadmin_client: AsyncClient):
    """Only a plain admin can be promoted to superadmin."""
    await register_and_verify(superadmin_client, "justuser@test.com")
    user_id = await get_user_id("justuser@test.com")

    response = await superadmin_client.post(f"/admin/admins/{user_id}/promote")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.NOT_AN_ADMIN


@pytest.mark.asyncio
async def test_promote_requires_root(
    superadmin_client: AsyncClient,
    nonroot_superadmin_client: AsyncClient,
):
    """A non-root superadmin cannot promote an admin to superadmin."""
    await register_and_verify(superadmin_client, "candidate@test.com")
    await promote_to_admin("candidate@test.com")
    user_id = await get_user_id("candidate@test.com")

    response = await nonroot_superadmin_client.post(f"/admin/admins/{user_id}/promote")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ONLY_ROOT_SUPERADMIN


# --- Demote superadmin -> admin (root only) ---------------------------------


@pytest.mark.asyncio
async def test_root_demotes_superadmin_to_admin(superadmin_client: AsyncClient):
    """The root superadmin can demote another superadmin back to admin."""
    await register_and_verify(superadmin_client, "fading@test.com")
    await promote_to_superadmin("fading@test.com")
    user_id = await get_user_id("fading@test.com")

    response = await superadmin_client.post(f"/admin/admins/{user_id}/demote")
    assert response.status_code == 200, response.text
    assert response.json()["admin"]["role"] == SystemRole.ADMIN.value
    assert response.json()["message"] == SuccessMessages.SUPERADMIN_DEMOTED


@pytest.mark.asyncio
async def test_demote_non_superadmin_rejected(superadmin_client: AsyncClient):
    """Only a superadmin can be demoted via this endpoint."""
    await register_and_verify(superadmin_client, "plainadmin@test.com")
    await promote_to_admin("plainadmin@test.com")
    user_id = await get_user_id("plainadmin@test.com")

    response = await superadmin_client.post(f"/admin/admins/{user_id}/demote")
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.NOT_A_SUPERADMIN


@pytest.mark.asyncio
async def test_root_cannot_demote_self(superadmin_client: AsyncClient):
    """The root superadmin's own role is immutable (use root transfer instead)."""
    root_id = await get_user_id("superadmin@test.com")

    response = await superadmin_client.post(f"/admin/admins/{root_id}/demote")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.SUPERADMIN_ROLE_IMMUTABLE


@pytest.mark.asyncio
async def test_demote_requires_root(
    superadmin_client: AsyncClient,
    nonroot_superadmin_client: AsyncClient,
):
    """A non-root superadmin cannot demote another superadmin."""
    await register_and_verify(superadmin_client, "target-super@test.com")
    await promote_to_superadmin("target-super@test.com")
    user_id = await get_user_id("target-super@test.com")

    response = await nonroot_superadmin_client.post(f"/admin/admins/{user_id}/demote")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ONLY_ROOT_SUPERADMIN


@pytest.mark.asyncio
async def test_admin_management_is_superadmin_only(admin_client: AsyncClient):
    """A plain admin — even with every permission — cannot manage admins."""
    response = await admin_client.get("/admin/admins")
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ONLY_SUPERADMIN_ALLOWED
