from pydantic import BaseModel
from app.schemas.user import UserPublic


# JSON payload containing access token
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(Token):
    user: UserPublic


class AuthTokens(Token):
    refresh_token: str
    user: UserPublic


# Contents of JWT token
class TokenPayload(BaseModel):
    sub: str | None = None
