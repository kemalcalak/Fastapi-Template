"""Shared fixtures and helpers for the /admin endpoint tests.

Kept in a sub-conftest so every file under ``app/tests/admin/`` gets the
admin-authenticated client and the seed helpers without re-importing them.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.main import app
from app.models.admin_permission import AdminPermission
from app.models.user import User
from app.schemas.admin_permission import Permission
from app.schemas.user import SystemRole
from app.tests.conftest import TestingSessionLocal


async def register_and_verify(
    client: AsyncClient,
    email: str,
    password: str = "Password123!",
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


async def promote_to_superadmin(email: str, *, root: bool = False) -> None:
    """Directly flip a user's role to superadmin in the DB.

    ``root=True`` also sets ``is_root_superadmin`` so the account can exercise
    the root-only actions (promote/demote a superadmin, transfer root).
    """
    async with TestingSessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.email == email)
            .values(role=SystemRole.SUPERADMIN.value, is_root_superadmin=root)
        )
        await session.commit()


async def grant_permissions(email: str, permissions: list[Permission]) -> None:
    """Grant the given RBAC permissions to an (already-admin) user."""
    async with TestingSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().one()
        for permission in permissions:
            session.add(AdminPermission(user_id=user.id, permission=permission.value))
        await session.commit()


async def grant_all_permissions(email: str) -> None:
    """Grant every RBAC permission so a plain admin passes all gate checks."""
    await grant_permissions(email, list(Permission))


async def login(
    client: AsyncClient, email: str, password: str = "Password123!"
) -> None:
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
async def superadmin_client(client: AsyncClient) -> AsyncClient:
    """Return an authenticated **root** superadmin client.

    Superadmins bypass the per-permission gate; the root flag additionally
    unlocks the superadmin-tier actions (promote/demote a superadmin, transfer
    root), which is where most admin-management tests drive their actor.
    """
    await register_and_verify(client, "superadmin@test.com")
    await promote_to_superadmin("superadmin@test.com", root=True)
    await login(client, "superadmin@test.com")
    return client


@pytest.fixture
async def nonroot_superadmin_client() -> AsyncClient:
    """A second superadmin that is NOT root, on an independent cookie jar.

    Used to assert the root-only guard: a plain superadmin must be refused the
    promote/demote/transfer-root actions. Built as its own client so it can
    coexist with the root ``superadmin_client`` in a single test.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url=f"http://test{settings.API_V1_STR}"
    ) as ac:
        await register_and_verify(ac, "superadmin2@test.com")
        await promote_to_superadmin("superadmin2@test.com", root=False)
        await login(ac, "superadmin2@test.com")
        yield ac


@pytest.fixture
async def regular_client(client: AsyncClient) -> AsyncClient:
    """Return an authenticated client whose user has the default user role."""
    await register_and_verify(client, "user@test.com")
    await login(client, "user@test.com")
    return client
