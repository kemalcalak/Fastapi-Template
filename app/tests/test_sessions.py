"""Tests for the session/device management feature.

Covers the user endpoints (/users/me/sessions), the session binding inside
the auth flows (login/refresh/logout/change-password), the admin endpoints
with RBAC, and the stale-session purge worker job.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.security import create_refresh_token, get_password_hash
from app.main import app
from app.models.user import User
from app.models.user_session import UserSession
from app.schemas.admin_permission import Permission
from app.tests.admin.conftest import (
    grant_permissions,
    promote_to_admin,
    register_and_verify,
)
from app.tests.conftest import TestingSessionLocal
from app.utils import utc_now

PASSWORD = "Password123!"

_UA_WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0 Safari/537.36"
_UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4) CriOS/125.0 Mobile Safari/604.1"


def _fresh_client() -> AsyncClient:
    """Cookie-isolated client simulating a separate device."""
    return AsyncClient(
        transport=ASGITransport(app=app), base_url=f"http://test{settings.API_V1_STR}"
    )


async def _login(client: AsyncClient, email: str, *, user_agent: str) -> None:
    """Login on the given client with a specific device user-agent."""
    resp = await client.post(
        "/auth/login",
        data={"username": email, "password": PASSWORD},
        headers={"user-agent": user_agent},
    )
    assert resp.status_code == 200


async def _user_id(email: str) -> UUID:
    """Look up a user's id directly in the DB."""
    async with TestingSessionLocal() as session:
        user = (
            (await session.execute(select(User).where(User.email == email)))
            .scalars()
            .one()
        )
        return user.id


# ---------------------------------------------------------------------------
# /users/me/sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_creates_session_with_device_metadata(client: AsyncClient):
    await register_and_verify(client, "sess1@test.com")
    await _login(client, "sess1@test.com", user_agent=_UA_WINDOWS)

    resp = await client.get("/users/me/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1 and body["skip"] == 0 and body["limit"] == 50
    row = body["data"][0]
    assert row["is_current"] is True
    assert row["browser"] == "Chrome"
    assert row["os"] == "Windows"
    assert row["ip_address"] is not None


@pytest.mark.asyncio
async def test_list_sessions_pagination(client: AsyncClient):
    await register_and_verify(client, "sess2@test.com")
    await _login(client, "sess2@test.com", user_agent=_UA_WINDOWS)
    other = _fresh_client()
    await _login(other, "sess2@test.com", user_agent=_UA_IPHONE)
    await other.aclose()

    resp = await client.get("/users/me/sessions?skip=1&limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["data"]) == 1
    assert body["skip"] == 1 and body["limit"] == 1


@pytest.mark.asyncio
async def test_revoke_single_session_kills_its_access_token(client: AsyncClient):
    await register_and_verify(client, "sess3@test.com")
    await _login(client, "sess3@test.com", user_agent=_UA_WINDOWS)

    other = _fresh_client()
    await _login(other, "sess3@test.com", user_agent=_UA_IPHONE)

    listing = (await client.get("/users/me/sessions")).json()
    target = next(s for s in listing["data"] if not s["is_current"])

    resp = await client.delete(f"/users/me/sessions/{target['id']}")
    assert resp.status_code == 200
    assert resp.json()["message"] == SuccessMessages.SESSION_REVOKED

    # The other device's access token must die immediately.
    dead = await other.get("/users/me")
    assert dead.status_code == 401
    await other.aclose()


@pytest.mark.asyncio
async def test_revoke_foreign_or_unknown_session_returns_404(client: AsyncClient):
    await register_and_verify(client, "sess4@test.com")
    await register_and_verify(client, "sess4b@test.com")
    await _login(client, "sess4@test.com", user_agent=_UA_WINDOWS)

    victim = _fresh_client()
    await _login(victim, "sess4b@test.com", user_agent=_UA_IPHONE)
    victim_session = (await victim.get("/users/me/sessions")).json()["data"][0]

    # Someone else's session id and a random id both yield the same 404.
    for session_id in (victim_session["id"], str(uuid4())):
        resp = await client.delete(f"/users/me/sessions/{session_id}")
        assert resp.status_code == 404
        assert resp.json()["error"] == ErrorMessages.SESSION_NOT_FOUND

    # The victim is untouched.
    assert (await victim.get("/users/me")).status_code == 200
    await victim.aclose()


@pytest.mark.asyncio
async def test_revoke_other_sessions_keeps_current(client: AsyncClient):
    await register_and_verify(client, "sess5@test.com")
    await _login(client, "sess5@test.com", user_agent=_UA_WINDOWS)

    other1, other2 = _fresh_client(), _fresh_client()
    await _login(other1, "sess5@test.com", user_agent=_UA_IPHONE)
    await _login(other2, "sess5@test.com", user_agent=_UA_IPHONE)

    resp = await client.delete("/users/me/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["revoked"] == 2
    assert body["message"] == SuccessMessages.OTHER_SESSIONS_REVOKED

    assert (await other1.get("/users/me")).status_code == 401
    assert (await other2.get("/users/me")).status_code == 401
    await other1.aclose()
    await other2.aclose()

    # Current device still works and is the only session left.
    listing = (await client.get("/users/me/sessions")).json()
    assert listing["total"] == 1
    assert listing["data"][0]["is_current"] is True


# ---------------------------------------------------------------------------
# Auth-flow integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_removes_session_from_list(client: AsyncClient):
    await register_and_verify(client, "sess6@test.com")
    await _login(client, "sess6@test.com", user_agent=_UA_WINDOWS)
    await client.post("/auth/logout")

    await _login(client, "sess6@test.com", user_agent=_UA_WINDOWS)
    listing = (await client.get("/users/me/sessions")).json()
    assert listing["total"] == 1  # the logged-out session is gone


@pytest.mark.asyncio
async def test_refresh_rotates_session_jti(client: AsyncClient):
    await register_and_verify(client, "sess7@test.com")
    await _login(client, "sess7@test.com", user_agent=_UA_WINDOWS)
    user_id = await _user_id("sess7@test.com")

    async with TestingSessionLocal() as session:
        row = (
            (
                await session.execute(
                    select(UserSession).where(UserSession.user_id == user_id)
                )
            )
            .scalars()
            .one()
        )
        jti_before = row.refresh_jti

    resp = await client.post("/auth/refresh")
    assert resp.status_code == 200

    async with TestingSessionLocal() as session:
        row = (
            (
                await session.execute(
                    select(UserSession).where(UserSession.user_id == user_id)
                )
            )
            .scalars()
            .one()
        )
        assert row.refresh_jti != jti_before
        assert row.revoked_at is None

    # Still one single session — rotation must not create a second row.
    listing = (await client.get("/users/me/sessions")).json()
    assert listing["total"] == 1


@pytest.mark.asyncio
async def test_refresh_replay_revokes_whole_session(client: AsyncClient, fake_redis):
    """If the blacklist ever loses state, the jti match still kills replays."""
    await register_and_verify(client, "sess8@test.com")
    await _login(client, "sess8@test.com", user_agent=_UA_WINDOWS)
    old_refresh = client.cookies.get("refresh_token")

    resp = await client.post("/auth/refresh")
    assert resp.status_code == 200
    new_refresh = client.cookies.get("refresh_token")

    # Simulate a Redis wipe: the rotated-away token is no longer blacklisted.
    await fake_redis.flushall()

    # Replaying the stale token now hits the session-jti guard...
    client.cookies.set("refresh_token", old_refresh)
    replay = await client.post("/auth/refresh")
    assert replay.status_code == 401

    # ...which revokes the session, so even the *newest* token is dead.
    client.cookies.set("refresh_token", new_refresh)
    after = await client.post("/auth/refresh")
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_without_sid_rejected(client: AsyncClient):
    """Legacy refresh tokens (pre-session deploys) cannot be refreshed."""
    await register_and_verify(client, "sess9@test.com")
    user_id = await _user_id("sess9@test.com")

    legacy = create_refresh_token(user_id)  # no session_id -> no sid claim
    client.cookies.set("refresh_token", legacy)
    resp = await client.post("/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["error"] == ErrorMessages.INVALID_TOKEN


@pytest.mark.asyncio
async def test_change_password_revokes_every_session(client: AsyncClient):
    await register_and_verify(client, "sess10@test.com")
    await _login(client, "sess10@test.com", user_agent=_UA_WINDOWS)

    other = _fresh_client()
    await _login(other, "sess10@test.com", user_agent=_UA_IPHONE)

    resp = await client.patch(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NewPassword123!"},
    )
    assert resp.status_code == 200

    # Both devices are logged out everywhere.
    assert (await other.get("/users/me")).status_code == 401
    await other.aclose()

    async with TestingSessionLocal() as session:
        user_id = await _user_id("sess10@test.com")
        rows = (
            (
                await session.execute(
                    select(UserSession).where(UserSession.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert rows and all(r.revoked_at is not None for r in rows)


# ---------------------------------------------------------------------------
# Admin endpoints + RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_sessions_require_permission(client: AsyncClient):
    await register_and_verify(client, "sess11@test.com")
    target_id = await _user_id("sess11@test.com")

    await register_and_verify(client, "admin11@test.com")
    await promote_to_admin("admin11@test.com")
    admin = _fresh_client()
    await _login(admin, "admin11@test.com", user_agent=_UA_WINDOWS)

    assert (await admin.get(f"/admin/users/{target_id}/sessions")).status_code == 403
    assert (await admin.delete(f"/admin/users/{target_id}/sessions")).status_code == 403
    await admin.aclose()


@pytest.mark.asyncio
async def test_admin_lists_and_revokes_user_sessions(client: AsyncClient):
    await register_and_verify(client, "sess12@test.com")
    device1, device2 = _fresh_client(), _fresh_client()
    await _login(device1, "sess12@test.com", user_agent=_UA_WINDOWS)
    await _login(device2, "sess12@test.com", user_agent=_UA_IPHONE)
    target_id = await _user_id("sess12@test.com")

    await register_and_verify(client, "admin12@test.com")
    await promote_to_admin("admin12@test.com")
    await grant_permissions("admin12@test.com", [Permission.USERS_SESSIONS])
    admin = _fresh_client()
    await _login(admin, "admin12@test.com", user_agent=_UA_WINDOWS)

    listing = (await admin.get(f"/admin/users/{target_id}/sessions")).json()
    assert listing["total"] == 2
    # "Current" is meaningless for the admin view — never flagged.
    assert all(s["is_current"] is False for s in listing["data"])

    resp = await admin.delete(f"/admin/users/{target_id}/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["revoked"] == 2
    assert body["message"] == SuccessMessages.ADMIN_SESSIONS_REVOKED

    # Every device of the target dies immediately.
    assert (await device1.get("/users/me")).status_code == 401
    assert (await device2.get("/users/me")).status_code == 401
    await device1.aclose()
    await device2.aclose()

    # Unknown target user -> 404.
    resp = await admin.get(f"/admin/users/{uuid4()}/sessions")
    assert resp.status_code == 404
    await admin.aclose()


# ---------------------------------------------------------------------------
# Purge worker job
# ---------------------------------------------------------------------------


async def _insert_session(
    user_id: UUID,
    *,
    expires_in: timedelta,
    revoked_ago: timedelta | None = None,
) -> UUID:
    """Insert a raw session row for purge-job test setup."""
    async with TestingSessionLocal() as session:
        row = UserSession(
            user_id=user_id,
            refresh_jti=str(uuid4()),
            expires_at=utc_now() + expires_in,
            revoked_at=utc_now() - revoked_ago if revoked_ago else None,
        )
        session.add(row)
        await session.commit()
        return row.id


@pytest.mark.asyncio
async def test_purge_job_sweeps_expired_and_long_revoked(monkeypatch):
    import app.worker.jobs.purge_stale_sessions as mod

    monkeypatch.setattr(mod, "AsyncSessionLocal", TestingSessionLocal)

    async with TestingSessionLocal() as session:
        user = User(
            email="purge@test.com",
            hashed_password=get_password_hash(PASSWORD),
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    keep_active = await _insert_session(user_id, expires_in=timedelta(days=7))
    keep_recent_revoke = await _insert_session(
        user_id, expires_in=timedelta(days=7), revoked_ago=timedelta(days=1)
    )
    await _insert_session(user_id, expires_in=timedelta(days=-1))  # expired
    await _insert_session(  # revoked past retention
        user_id, expires_in=timedelta(days=7), revoked_ago=timedelta(days=40)
    )

    result = await mod.purge_stale_sessions({})
    assert result.purged == 2

    async with TestingSessionLocal() as session:
        remaining = {
            row.id
            for row in (
                (
                    await session.execute(
                        select(UserSession).where(UserSession.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
        }
    assert remaining == {keep_active, keep_recent_revoke}
