from pydantic import BaseModel

from app.schemas.user import UserPublic


# JSON payload containing access token
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    message: str | None = None


class AuthTokens(Token):
    refresh_token: str
    user: UserPublic
    message: str | None = None


class CookieLoginResponse(BaseModel):
    """Login response without access_token in body (token is in HttpOnly cookie)."""

    token_type: str = "bearer"
    user: UserPublic
    message: str | None = None


class CookieRefreshResponse(BaseModel):
    """Refresh response without access_token in body (token is in HttpOnly cookie)."""

    token_type: str = "bearer"
    message: str | None = None


# Contents of JWT token
class TokenPayload(BaseModel):
    sub: str | None = None
