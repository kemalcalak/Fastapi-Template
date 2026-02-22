from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/hour", "60/minute"],
    storage_uri="memory://",  # Use memory storage (for Redis: redis://localhost:6379)
    enabled=settings.ENVIRONMENT != "local",  # Disable in development
)


# Common rate limit decorators
def rate_limit_public(limit: str = "10/minute"):
    """Rate limit for public endpoints (no auth required).

    Args:
        limit: Rate limit string (e.g., "10/minute", "100/hour")

    Usage:
        @router.post("/login")
        @rate_limit_public("5/minute")
        async def login(request: Request, ...):
            ...
    """
    return limiter.limit(limit)


def rate_limit_authenticated(limit: str = "100/minute"):
    """Rate limit for authenticated endpoints.

    Args:
        limit: Rate limit string (e.g., "100/minute", "1000/hour")

    Usage:
        @router.get("/users/me")
        @rate_limit_authenticated("100/minute")
        async def get_me(request: Request, ...):
            ...
    """
    return limiter.limit(limit)


def rate_limit_strict(limit: str = "3/minute"):
    """Strict rate limit for sensitive endpoints (e.g., password reset).

    Args:
        limit: Rate limit string (e.g., "3/minute", "10/hour")

    Usage:
        @router.post("/reset-password")
        @rate_limit_strict("3/minute")
        async def reset_password(request: Request, ...):
            ...
    """
    return limiter.limit(limit)


# Rate limit by user ID (for authenticated requests)
def get_user_id(request: Request):
    """Extract user ID from request for rate limiting.

    Usage:
        limiter_user = Limiter(key_func=get_user_id)

        @router.post("/posts")
        @limiter_user.limit("10/minute")
        async def create_post(request: Request, ...):
            ...
    """
    # Extract user ID from token or request state
    # This is a placeholder - implement based on your auth logic
    user = getattr(request.state, "user", None)
    if user:
        return str(user.id)
    return get_remote_address(request)
