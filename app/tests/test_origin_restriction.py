import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.mark.asyncio
async def test_allowed_origin(client: AsyncClient):
    # Use an origin from settings.all_cors_origins
    # settings.all_cors_origins includes FRONTEND_HOST
    allowed_origin = settings.FRONTEND_HOST
    response = await client.get(
        "/users/me",  # Correct path
        headers={"Origin": allowed_origin},
    )
    # It should not be 404 due to origin (might be 401 if not logged in, but not 404)
    assert response.status_code != 404


@pytest.mark.asyncio
async def test_unauthorized_origin(client: AsyncClient):
    response = await client.get(
        "/auth/login",  # Use an endpoint that exists
        headers={"Origin": "http://malicious.com"},
    )
    assert response.status_code == 404
    assert response.json() == {"success": False, "error": "RESOURCE_NOT_FOUND"}


@pytest.mark.asyncio
async def test_no_origin(client: AsyncClient):
    response = await client.get("/auth/login")
    # Should not be 404 due to missing origin
    assert response.status_code != 404
    # If /health doesn't exist, this might fail, but let's check a known endpoint
    pass


@pytest.mark.asyncio
async def test_same_origin_post(client: AsyncClient):
    """Test that same-origin POST requests are allowed (not blocked with 404)."""
    # The client fixture uses http://test as the base origin (from conftest base_url)
    same_origin = "http://test"

    response = await client.post(
        "/auth/logout",  # Correct path (base_url already includes /api/v1)
        headers={"Origin": same_origin},
    )

    # Should NOT be 404 due to origin check (may fail with 401 if not authenticated, but not 404)
    assert response.status_code != 404, (
        "Same-origin POST request should not be blocked with 404"
    )


@pytest.mark.asyncio
async def test_same_origin_put(client: AsyncClient):
    """Test that same-origin PUT requests are allowed (not blocked with 404)."""
    same_origin = "http://test"

    response = await client.put(
        "/users/me",
        headers={"Origin": same_origin},
    )

    # Should NOT be 404 due to origin check (may fail with 401/422, but not 404)
    assert response.status_code != 404, (
        "Same-origin PUT request should not be blocked with 404"
    )


@pytest.mark.asyncio
async def test_cross_origin_post_blocked(client: AsyncClient):
    """Test that cross-origin POST requests are still blocked (404)."""
    response = await client.post(
        "/auth/logout",
        headers={"Origin": "http://malicious.com"},
    )

    assert response.status_code == 404
    assert response.json() == {"success": False, "error": "RESOURCE_NOT_FOUND"}
