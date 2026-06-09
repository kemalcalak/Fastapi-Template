"""Tests for the email-OTP root-superadmin transfer flow."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.user import User
from app.tests.admin.conftest import (
    get_user_id,
    promote_to_admin,
    promote_to_superadmin,
    register_and_verify,
)
from app.tests.conftest import TestingSessionLocal


def _extract_code(email_mock) -> str:
    """Pull the 6-digit OTP out of the most recent transfer email."""
    plain_text = email_mock.call_args.kwargs["plain_text"]
    match = re.search(r"\d{6}", plain_text)
    assert match, plain_text
    return match.group()


async def _is_root(email: str) -> bool:
    """Read the persisted root flag for an account."""
    async with TestingSessionLocal() as session:
        user = (
            (await session.execute(select(User).where(User.email == email)))
            .scalars()
            .one()
        )
        return user.is_root_superadmin


@pytest.mark.asyncio
async def test_root_transfer_otp_flow(superadmin_client: AsyncClient, mock_email_send):
    """Happy path: OTP is emailed to the root, then confirmed to move root."""
    await register_and_verify(superadmin_client, "heir@test.com")
    await promote_to_superadmin("heir@test.com")
    heir_id = await get_user_id("heir@test.com")

    initiate = await superadmin_client.post(
        "/admin/admins/transfer-root", json={"user_id": heir_id}
    )
    assert initiate.status_code == 200, initiate.text
    assert initiate.json()["message"] == SuccessMessages.ROOT_TRANSFER_INITIATED
    # OTP goes to the *current* root's own address, never the target's.
    assert mock_email_send.call_args.kwargs["to"] == "superadmin@test.com"

    code = _extract_code(mock_email_send)
    confirm = await superadmin_client.post(
        "/admin/admins/transfer-root/confirm", json={"code": code}
    )
    assert confirm.status_code == 200, confirm.text
    admin = confirm.json()["admin"]
    assert admin["id"] == heir_id
    assert admin["is_root_superadmin"] is True
    assert confirm.json()["message"] == SuccessMessages.ROOT_TRANSFERRED

    assert await _is_root("heir@test.com") is True
    assert await _is_root("superadmin@test.com") is False


@pytest.mark.asyncio
async def test_transfer_root_requires_root(
    nonroot_superadmin_client: AsyncClient,
):
    """A non-root superadmin cannot initiate a root transfer."""
    # Target is the actor itself (a superadmin); the root check fails first.
    target_id = await get_user_id("superadmin2@test.com")

    response = await nonroot_superadmin_client.post(
        "/admin/admins/transfer-root", json={"user_id": target_id}
    )
    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ONLY_ROOT_SUPERADMIN


@pytest.mark.asyncio
async def test_transfer_root_target_must_be_superadmin(superadmin_client: AsyncClient):
    """Root status can only be transferred to another superadmin."""
    await register_and_verify(superadmin_client, "plain-admin@test.com")
    await promote_to_admin("plain-admin@test.com")
    target_id = await get_user_id("plain-admin@test.com")

    response = await superadmin_client.post(
        "/admin/admins/transfer-root", json={"user_id": target_id}
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.NOT_A_SUPERADMIN


@pytest.mark.asyncio
async def test_transfer_root_to_self_rejected(superadmin_client: AsyncClient):
    """The root cannot transfer root status to itself."""
    root_id = await get_user_id("superadmin@test.com")

    response = await superadmin_client.post(
        "/admin/admins/transfer-root", json={"user_id": root_id}
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.CANNOT_TRANSFER_TO_SELF


@pytest.mark.asyncio
async def test_confirm_wrong_code_rejected(superadmin_client: AsyncClient):
    """An incorrect OTP is refused and root status is unchanged."""
    await register_and_verify(superadmin_client, "heir2@test.com")
    await promote_to_superadmin("heir2@test.com")
    heir_id = await get_user_id("heir2@test.com")

    await superadmin_client.post(
        "/admin/admins/transfer-root", json={"user_id": heir_id}
    )

    response = await superadmin_client.post(
        "/admin/admins/transfer-root/confirm", json={"code": "000000"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.INVALID_VERIFICATION_TOKEN
    assert await _is_root("superadmin@test.com") is True


@pytest.mark.asyncio
async def test_confirm_without_pending_rejected(superadmin_client: AsyncClient):
    """Confirming with no pending transfer is refused."""
    response = await superadmin_client.post(
        "/admin/admins/transfer-root/confirm", json={"code": "123456"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == ErrorMessages.INVALID_VERIFICATION_TOKEN
