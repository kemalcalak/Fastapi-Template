"""End-to-end tests for the /admin/support endpoints.

Covers the admin queue (list/filter/search), replying with self-assignment,
status/priority/assignment updates with validation, and the shared-queue
behaviour where any admin may answer any ticket.
"""

import pytest

from app.core.messages.error_message import ErrorMessages
from app.schemas.support import SenderRole, TicketPriority, TicketStatus
from app.tests.support.conftest import (
    ClientFactory,
    make_admin_client,
    make_user_client,
    open_ticket,
)


def user_id_of(ticket: dict) -> str:
    """Return the owner id from a user-facing ticket payload's first message."""
    return ticket["messages"][0]["sender_id"]


@pytest.mark.asyncio
async def test_requires_admin(client_factory: ClientFactory):
    """A regular user is forbidden from the admin queue."""
    user = await make_user_client(client_factory, "u1@test.com")

    response = await user.get("/admin/support/tickets")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(client_factory: ClientFactory):
    """An anonymous caller is unauthorized, not merely forbidden."""
    anon = await client_factory()

    response = await anon.get("/admin/support/tickets")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_and_filter(client_factory: ClientFactory):
    """The queue lists every ticket and honours search/status filters."""
    user = await make_user_client(client_factory, "u1@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    await open_ticket(user, subject="Payment issue")
    await open_ticket(user, subject="Login issue")

    response = await admin.get("/admin/support/tickets")
    assert response.status_code == 200
    assert response.json()["total"] == 2

    response = await admin.get("/admin/support/tickets?search=Payment")
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["subject"] == "Payment issue"
    assert body["data"][0]["user"]["email"] == "u1@test.com"

    response = await admin.get(
        f"/admin/support/tickets?status={TicketStatus.OPEN.value}"
    )
    assert response.json()["total"] == 2


@pytest.mark.asyncio
async def test_search_by_user_email(client_factory: ClientFactory):
    """Admin search also matches the ticket owner's email."""
    user = await make_user_client(client_factory, "needle@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    await open_ticket(user)

    response = await admin.get("/admin/support/tickets?search=needle")

    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_reply_self_assigns_and_pends(client_factory: ClientFactory):
    """An admin reply self-assigns the ticket and sets status to pending."""
    user = await make_user_client(client_factory, "u1@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(user)

    response = await admin.post(
        f"/admin/support/tickets/{ticket['id']}/messages",
        json={"body": "Looking into it"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["sender_role"] == SenderRole.ADMIN.value

    detail = await admin.get(f"/admin/support/tickets/{ticket['id']}")
    body = detail.json()
    assert body["status"] == TicketStatus.PENDING.value
    assert body["assigned_admin_id"] is not None


@pytest.mark.asyncio
async def test_update_status_and_priority(client_factory: ClientFactory):
    """Updating status to closed sets closed_at; reopening clears it."""
    user = await make_user_client(client_factory, "u1@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(user)

    response = await admin.patch(
        f"/admin/support/tickets/{ticket['id']}",
        json={
            "status": TicketStatus.CLOSED.value,
            "priority": TicketPriority.HIGH.value,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == TicketStatus.CLOSED.value
    assert body["priority"] == TicketPriority.HIGH.value
    assert body["closed_at"] is not None

    response = await admin.patch(
        f"/admin/support/tickets/{ticket['id']}",
        json={"status": TicketStatus.OPEN.value},
    )
    assert response.json()["closed_at"] is None


@pytest.mark.asyncio
async def test_assign_to_non_admin_rejected(client_factory: ClientFactory):
    """Assigning a ticket to a non-admin user returns 422."""
    user = await make_user_client(client_factory, "u1@test.com")
    admin = await make_admin_client(client_factory, "admin@test.com")
    ticket = await open_ticket(user)

    # The ticket owner (a regular user) is not a valid assignee.
    response = await admin.patch(
        f"/admin/support/tickets/{ticket['id']}",
        json={"assigned_admin_id": user_id_of(ticket)},
    )

    assert response.status_code == 422
    assert response.json()["error"] == ErrorMessages.INVALID_ASSIGNED_ADMIN


@pytest.mark.asyncio
async def test_shared_queue_second_admin_can_reply(
    client_factory: ClientFactory,
):
    """After one admin self-assigns, another admin may still reply."""
    user = await make_user_client(client_factory, "u1@test.com")
    admin_a = await make_admin_client(client_factory, "admina@test.com")
    admin_b = await make_admin_client(client_factory, "adminb@test.com")
    ticket = await open_ticket(user)

    first = await admin_a.post(
        f"/admin/support/tickets/{ticket['id']}/messages",
        json={"body": "Admin A here"},
    )
    assert first.status_code == 201

    second = await admin_b.post(
        f"/admin/support/tickets/{ticket['id']}/messages",
        json={"body": "Admin B stepping in"},
    )
    assert second.status_code == 201, second.text
