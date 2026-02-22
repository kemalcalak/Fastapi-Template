import pytest
from fastapi import APIRouter, Request
from httpx import AsyncClient

from app.core.rate_limit import limiter, rate_limit_public
from app.main import app
from app.core.config import settings

dummy_router = APIRouter()


@dummy_router.get("/dummy-rate-limit", tags=["test"])
@rate_limit_public("2/minute")
async def dummy_rate_limit_endpoint(request: Request):
    return {"message": "success"}


app.include_router(dummy_router, prefix=settings.API_V1_STR)


@pytest.mark.asyncio
async def test_rate_limiter_exceed(client: AsyncClient):
    # Enable rate limiting for the test
    original_enabled = limiter.enabled
    limiter.enabled = True

    try:
        # 1st request
        response = await client.get("/dummy-rate-limit")
        assert response.status_code == 200

        # 2nd request
        response = await client.get("/dummy-rate-limit")
        assert response.status_code == 200

        # 3rd request - should be blocked by rate limit
        response = await client.get("/dummy-rate-limit")
        assert response.status_code == 429
        data = response.json()
        assert "error" in data or "detail" in data
    finally:
        limiter.enabled = original_enabled
