"""Shared fixtures and helpers for the /admin endpoint tests.

Kept in a sub-conftest so every file under ``app/tests/admin/`` gets the
admin-authenticated client and the seed helpers without re-importing them.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.models.admin_permission import AdminPermission
from app.models.user import User
from app.schemas.admin_permission import Permission
from app.schemas.user import SystemRole
from app.tests.conftest import TestingSessionLocal


async def register_and_verify(
    client: AsyncClient,
    email: str,
    password: str = "password123",
) -> None:
    """Register a user and mark them verified so they can log in."""
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "F",
            "last_name": "L",
            "title": "T",
        },
    )
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == email).values(is_verified=True)
        )
        await session.commit()


async def promote_to_admin(email: str) -> None:
    """Directly flip a user's role to admin in the DB."""
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == email).values(role=SystemRole.ADMIN.value)
        )
        await session.commit()


async def promote_to_superadmin(email: str) -> None:
    """Directly flip a user's role to superadmin in the DB."""
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.email == email)
            .values(role=SystemRole.SUPERADMIN.value)
        )
        await session.commit()


async def grant_permissions(email: str, permissions: list[Permission]) -> None:
    """Grant the given RBAC permissions to an (already-admin) user."""
    async with TestingSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().one()
        for permission in permissions:
            session.add(
                AdminPermission(user_id=user.id, permission=permission.value)
            )
        await session.commit()


async def grant_all_permissions(email: str) -> None:
    """Grant every RBAC permission so a plain admin passes all gate checks."""
    await grant_permissions(email, list(Permission))


async def login(client: AsyncClient, email: str, password: str = "password123") -> None:
    """Log in and let httpx store the returned auth cookies on the client."""
    response = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text


async def get_user_id(email: str) -> str:
    """Resolve a user's UUID from their email for use in path params."""
    async with TestingSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        return str(result.scalars().one().id)


@pytest.fixture
async def admin_client(client: AsyncClient) -> AsyncClient:
    """Return an authenticated admin client holding every RBAC permission.

    Stays role ``admin`` (not superadmin) so admin-tier counting and last-admin
    guards behave as before; all permissions are granted so the per-permission
    route gate passes. Superadmin-specific behaviour is covered separately.
    """
    await register_and_verify(client, "admin@test.com")
    await promote_to_admin("admin@test.com")
    await grant_all_permissions("admin@test.com")
    await login(client, "admin@test.com")
    return client


@pytest.fixture
async def regular_client(client: AsyncClient) -> AsyncClient:
    """Return an authenticated client whose user has the default user role."""
    await register_and_verify(client, "user@test.com")
    await login(client, "user@test.com")
    return client
