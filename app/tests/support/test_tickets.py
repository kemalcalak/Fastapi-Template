"""End-to-end tests for the user-facing /support/tickets endpoints.

Covers the ticket lifecycle, ownership isolation, closed-ticket guards, and
attachment validation.
"""

import pytest

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.schemas.support import SenderRole, TicketStatus
from app.tests.support.conftest import (
    ClientFactory,
    make_admin_client,
    make_user_client,
    open_ticket,
    upload_png,
)


@pytest.mark.asyncio
async def test_create_ticket(client_factory: ClientFactory):
    """Opening a ticket returns it open with one user-authored message."""
    user = await make_user_client(client_factory, "u1@test.com")

    response = await user.post(
        "/support/tickets",
        json={"subject": "Login fails", "body": "I cannot log in"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["message"] == SuccessMessages.TICKET_CREATED
    ticket = body["ticket"]
    assert ticket["status"] == TicketStatus.OPEN.value
    assert ticket["subject"] == "Login fails"
    assert len(ticket["messages"]) == 1
    assert ticket["messages"][0]["sender_role"] == SenderRole.USER.value


@pytest.mark.asyncio
async def test_create_with_attachment(client_factory: ClientFactory):
    """An uploaded file can be attached to the opening message."""
    user = await make_user_client(client_factory, "u1@test.com")
    file_id = await upload_png(user)

    ticket = await open_ticket(user, attachment_file_ids=[file_id])

    attachments = ticket["messages"][0]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["file"]["id"] == file_id


@pytest.mark.asyncio
async def test_attachment_ownership_rejected(client_factory: ClientFactory):
    """A user cannot attach a file uploaded by someone else (IDOR guard)."""
    owner = await make_user_client(client_factory, "owner@test.com")
    other = await make_user_client(client_factory, "other@test.com")
    foreign_file = await upload_png(owner)

    response = await other.post(
        "/support/tickets",
        json={
            "subject": "Sneaky",
            "body": "Using another user's file",
            "attachment_file_ids": [foreign_file],
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.ATTACHMENT_NOT_OWNED


@pytest.mark.asyncio
async def test_list_only_my_tickets(client_factory: ClientFactory):
    """Listing returns only the caller's own tickets."""
    user = await make_user_client(client_factory, "u1@test.com")
    other = await make_user_client(client_factory, "u2@test.com")
    await open_ticket(user, subject="Mine")
    await open_ticket(other, subject="Theirs")

    response = await user.get("/support/tickets")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["subject"] == "Mine"


@pytest.mark.asyncio
async def test_get_other_users_ticket_forbidden(client_factory: ClientFactory):
    """Reading a ticket you do not own returns 403."""
    owner = await make_user_client(client_factory, "owner@test.com")
    other = await make_user_client(client_factory, "other@test.com")
    ticket = await open_ticket(owner)

    response = await other.get(f"/support/tickets/{ticket['id']}")

    assert response.status_code == 403
    assert response.json()["error"] == ErrorMessages.TICKET_ACCESS_DENIED


@pytest.mark.asyncio
async def test_get_nonexistent_ticket_404(client_factory: ClientFactory):
    """A missing ticket returns 404."""
    user = await make_user_client(client_factory, "u1@test.com")

    response = await user.get("/support/tickets/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"] == ErrorMessages.TICKET_NOT_FOUND


@pytest.mark.asyncio
async def test_reply_sets_status_answered(client_factory: ClientFactory):
    """A user reply moves the ticket into the 'answered' state."""
    user = await make_user_client(client_factory, "u1@test.com")
    ticket = await open_ticket(user)

    response = await user.post(
        f"/support/tickets/{ticket['id']}/messages",
        json={"body": "Any update?"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["sender_role"] == SenderRole.USER.value

    detail = await user.get(f"/support/tickets/{ticket['id']}")
    assert detail.json()["status"] == TicketStatus.ANSWERED.value


@pytest.mark.asyncio
async def test_reply_to_closed_ticket_conflict(client_factory: ClientFactory):
    """Replying to a closed ticket returns 409."""
    user = await make_user_client(client_factory, "u1@test.com")
    ticket = await open_ticket(user)
    await user.post(f"/support/tickets/{ticket['id']}/close")

    response = await user.post(
        f"/support/tickets/{ticket['id']}/messages",
        json={"body": "reopen please"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == ErrorMessages.TICKET_ALREADY_CLOSED


@pytest.mark.asyncio
async def test_close_ticket(client_factory: ClientFactory):
    """Closing a ticket sets its status and closed_at timestamp."""
    user = await make_user_client(client_factory, "u1@test.com")
    ticket = await open_ticket(user)

    response = await user.post(f"/support/tickets/{ticket['id']}/close")

    assert response.status_code == 200, response.text
    closed = response.json()["ticket"]
    assert closed["status"] == TicketStatus.CLOSED.value
    assert closed["closed_at"] is not None


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(client_factory: ClientFactory):
    """An anonymous caller cannot list tickets."""
    anon = await client_factory()

    response = await anon.get("/support/tickets")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unread_count_reflects_admin_reply(client_factory: ClientFactory):
    """An admin reply bumps the user's unread count until they read it."""
    user = await make_user_client(client_factory, "u1@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(user)

    await admin.post(
        f"/admin/support/tickets/{ticket['id']}/messages",
        json={"body": "We are on it"},
    )

    listing = await user.get("/support/tickets")
    assert listing.json()["data"][0]["unread_count"] == 1

    # Opening the thread marks the admin message read.
    await user.get(f"/support/tickets/{ticket['id']}")
    listing = await user.get("/support/tickets")
    assert listing.json()["data"][0]["unread_count"] == 0
