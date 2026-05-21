import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.messages.success_message import SuccessMessages
from app.models.user_activity import UserActivity
from app.schemas.user_activity import ActivityType, ResourceType
from app.tests.conftest import TestingSessionLocal

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


async def _upload(client: AsyncClient, name: str = "a.png") -> str:
    """Upload a PNG via the client and return the new file's id."""
    response = await client.post(
        "/upload", files={"file": (name, PNG_BYTES, "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_admin_list_files(admin_client: AsyncClient):
    """The admin listing returns uploaded files with internal fields."""
    await _upload(admin_client, "one.png")
    await _upload(admin_client, "two.png")

    response = await admin_client.get("/admin/files")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert len(body["data"]) == 2
    first = body["data"][0]
    assert "public_id" in first
    assert "uploaded_by_id" in first
    # The resolved uploader is embedded so the UI can show who uploaded it.
    assert first["uploaded_by"]["email"] == "admin@test.com"


@pytest.mark.asyncio
async def test_admin_list_files_filter_content_type(admin_client: AsyncClient):
    """Filtering by content_type narrows the result set."""
    await _upload(admin_client)

    match = await admin_client.get("/admin/files", params={"content_type": "image/png"})
    assert match.json()["total"] == 1

    miss = await admin_client.get("/admin/files", params={"content_type": "image/gif"})
    assert miss.json()["total"] == 0


@pytest.mark.asyncio
async def test_admin_list_files_filter_uploader(admin_client: AsyncClient):
    """Filtering by uploader matches the uploader's name or email."""
    await _upload(admin_client)

    # The admin fixture uploads as admin@test.com (first_name "F").
    by_email = await admin_client.get("/admin/files", params={"uploader": "admin@test"})
    assert by_email.json()["total"] == 1

    by_name = await admin_client.get("/admin/files", params={"uploader": "F"})
    assert by_name.json()["total"] == 1

    miss = await admin_client.get("/admin/files", params={"uploader": "nobody-xyz"})
    assert miss.json()["total"] == 0


@pytest.mark.asyncio
async def test_admin_get_file_detail(admin_client: AsyncClient):
    """The detail endpoint returns a single file's admin view."""
    file_id = await _upload(admin_client)
    response = await admin_client.get(f"/admin/files/{file_id}")
    assert response.status_code == 200
    assert response.json()["id"] == file_id


@pytest.mark.asyncio
async def test_admin_get_missing_file_404(admin_client: AsyncClient):
    """Fetching an unknown file id returns 404."""
    response = await admin_client.get(f"/admin/files/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_delete_file(admin_client: AsyncClient, mock_cloudinary):
    """Deleting a file removes the Cloudinary asset, the row, and logs it."""
    file_id = await _upload(admin_client)

    response = await admin_client.delete(f"/admin/files/{file_id}")
    assert response.status_code == 200
    assert response.json()["message"] == SuccessMessages.ADMIN_FILE_DELETED
    assert mock_cloudinary.delete.called

    async with TestingSessionLocal() as session:
        gone = await admin_client.get(f"/admin/files/{file_id}")
        assert gone.status_code == 404
        logged = (
            await session.execute(
                select(func.count())
                .select_from(UserActivity)
                .where(
                    UserActivity.resource_type == ResourceType.FILE.value,
                    UserActivity.activity_type == ActivityType.DELETE.value,
                )
            )
        ).scalar_one()
        assert logged >= 1


@pytest.mark.asyncio
async def test_admin_delete_file_clears_avatar(admin_client: AsyncClient):
    """Deleting a file that is in use as an avatar nulls the reference."""
    file_id = await _upload(admin_client)
    await admin_client.patch("/users/me", json={"avatar_file_id": file_id})

    before = await admin_client.get("/users/me")
    assert before.json()["avatar_file"]["id"] == file_id

    delete = await admin_client.delete(f"/admin/files/{file_id}")
    assert delete.status_code == 200

    after = await admin_client.get("/users/me")
    assert after.json()["avatar_file"] is None


@pytest.mark.asyncio
async def test_admin_files_requires_superuser(regular_client: AsyncClient):
    """A non-admin user cannot reach the admin file endpoints."""
    response = await regular_client.get("/admin/files")
    assert response.status_code == 403
