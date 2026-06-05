import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.config import settings
from app.models.file import File
from app.models.user import User
from app.tests.conftest import TestingSessionLocal

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


async def _register_verify_login(
    client: AsyncClient, email: str, password: str = "password123"
) -> None:
    """Register a user, mark them verified, and log in on the client."""
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
    response = await client.post(
        "/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 200, response.text


async def _upload(
    client: AsyncClient,
    *,
    name: str = "a.png",
    data: bytes = PNG_BYTES,
    content_type: str = "image/png",
) -> object:
    """POST a file to /upload and return the response."""
    return await client.post("/upload", files={"file": (name, data, content_type)})


@pytest.mark.asyncio
async def test_upload_requires_auth(client: AsyncClient):
    """Anonymous callers cannot upload."""
    response = await _upload(client)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_success(client: AsyncClient):
    """A valid image upload returns 201 with the stored file metadata."""
    await _register_verify_login(client, "u@test.com")
    response = await _upload(client)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["url"] == "https://cdn.test/img.png"
    assert data["content_type"] == "image/png"
    assert data["size"] == len(PNG_BYTES)
    assert "id" in data
    assert "public_id" not in data  # internal field stays hidden
    assert data["category"] == "general"  # default bucket


@pytest.mark.asyncio
async def test_upload_category_buckets_into_folder(
    client: AsyncClient, mock_cloudinary
):
    """A category tags the file and routes it to its Cloudinary sub-folder."""
    await _register_verify_login(client, "u@test.com")

    response = await client.post(
        "/upload",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
        data={"category": "support_attachment"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["category"] == "support_attachment"

    folder = mock_cloudinary.upload.call_args.kwargs["folder"]
    assert folder.startswith(f"{settings.CLOUDINARY_UPLOAD_FOLDER}/support_attachment/")


@pytest.mark.asyncio
async def test_upload_rejects_unknown_category(client: AsyncClient):
    """An unrecognised category fails validation rather than being stored."""
    await _register_verify_login(client, "u@test.com")

    response = await client.post(
        "/upload",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
        data={"category": "not_a_real_bucket"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_invalid_mime_rejected(client: AsyncClient):
    """Non-image content types are rejected with 415."""
    await _register_verify_login(client, "u@test.com")
    response = await _upload(client, name="a.pdf", content_type="application/pdf")
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_upload_empty_rejected(client: AsyncClient):
    """An empty file body is rejected with 400."""
    await _register_verify_login(client, "u@test.com")
    response = await _upload(client, data=b"")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_too_large_rejected(client: AsyncClient, monkeypatch):
    """Files over MAX_UPLOAD_SIZE_BYTES are rejected with 413."""
    await _register_verify_login(client, "u@test.com")
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 4)
    response = await _upload(client, data=b"too-many-bytes")
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_set_avatar_via_patch_me(client: AsyncClient):
    """Uploading then attaching the file surfaces the avatar on /users/me."""
    await _register_verify_login(client, "u@test.com")
    file_id = (await _upload(client)).json()["id"]

    patch_resp = await client.patch("/users/me", json={"avatar_file_id": file_id})
    assert patch_resp.status_code == 200, patch_resp.text

    me = await client.get("/users/me")
    assert me.status_code == 200
    avatar = me.json()["avatar_file"]
    assert avatar is not None
    assert avatar["id"] == file_id
    assert avatar["url"] == "https://cdn.test/img.png"


@pytest.mark.asyncio
async def test_attach_others_file_forbidden(client: AsyncClient):
    """A user cannot attach a file uploaded by someone else (IDOR guard)."""
    await _register_verify_login(client, "owner@test.com")
    file_id = (await _upload(client)).json()["id"]

    # Switch to a different user on the same client.
    await _register_verify_login(client, "attacker@test.com")
    response = await client.patch("/users/me", json={"avatar_file_id": file_id})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_replace_avatar_deletes_old(client: AsyncClient, mock_cloudinary):
    """Replacing an avatar removes the previous file from Cloudinary and DB."""
    await _register_verify_login(client, "u@test.com")
    first_id = (await _upload(client)).json()["id"]
    await client.patch("/users/me", json={"avatar_file_id": first_id})

    second_id = (await _upload(client)).json()["id"]
    await client.patch("/users/me", json={"avatar_file_id": second_id})

    assert mock_cloudinary.delete.called
    async with TestingSessionLocal() as session:
        assert await session.get(File, uuid.UUID(first_id)) is None
        assert await session.get(File, uuid.UUID(second_id)) is not None
