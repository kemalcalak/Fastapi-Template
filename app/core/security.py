import uuid
from datetime import datetime, timedelta

import jwt
import bcrypt

from app.core.config import settings
from app.utils import utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_payload(subject: str, token_type: str, expire: datetime) -> dict:
    """Build a standard JWT payload with UTC unix timestamps."""
    now = utc_now()
    return {
        "sub": subject,
        "type": token_type,
        "jti": str(uuid.uuid4()),
        "iat": now.timestamp(),
        "exp": expire.timestamp(),
    }


# ---------------------------------------------------------------------------
# Access & Refresh tokens
# ---------------------------------------------------------------------------


def create_access_token(
    subject: str | uuid.UUID,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a short-lived JWT access token.

    Args:
        subject:       User ID (str or UUID)
        expires_delta: Optional custom TTL

    Returns:
        Encoded JWT string
    """
    expire = utc_now() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = _base_payload(str(subject), "access", expire)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(
    subject: str | uuid.UUID,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a long-lived JWT refresh token.

    Store the ``jti`` in the DB / Redis so it can be revoked on logout.

    Args:
        subject:       User ID (str or UUID)
        expires_delta: Optional custom TTL

    Returns:
        Encoded JWT string
    """
    expire = utc_now() + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    payload = _base_payload(str(subject), "refresh", expire)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def verify_token(token: str, expected_type: str = "access") -> str | None:
    """
    Decode and validate a JWT token.

    Args:
        token:         Raw JWT string
        expected_type: ``"access"`` or ``"refresh"``

    Returns:
        Subject (user ID) on success, ``None`` otherwise
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != expected_type:
            return None
        subject: str | None = payload.get("sub")
        return subject if subject else None
    except jwt.PyJWTError:
        return None


def verify_refresh_token(token: str) -> str | None:
    """Convenience wrapper — verify a refresh token."""
    return verify_token(token, expected_type="refresh")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against its bcrypt hash.

    Args:
        plain_password:  Password provided by the user
        hashed_password: Hash stored in the database

    Returns:
        ``True`` if the password matches, ``False`` otherwise
    """
    try:
        if isinstance(hashed_password, str):
            hashed_password_bytes = hashed_password.encode('utf-8')
        else:
            hashed_password_bytes = hashed_password
            
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password_bytes
        )
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    """
    Hash a plain-text password with bcrypt.

    Args:
        password: Plain-text password

    Returns:
        bcrypt hash string
    """
    salt = bcrypt.gensalt(prefix=b"2b")
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


# ---------------------------------------------------------------------------
# Email verification tokens  (password-reset & new-account)
# ---------------------------------------------------------------------------


def _create_email_token(email: str, token_type: str) -> str:
    """
    Internal helper — builds a short-lived email action token.

    Both ``exp`` and ``nbf`` are stored as UNIX timestamps (floats) so they
    survive round-trips through PyJWT without timezone issues.
    """
    now = utc_now()
    expire = now + timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": email,
        "type": token_type,
        "jti": str(uuid.uuid4()),
        "iat": now.timestamp(),
        "nbf": now.timestamp(),
        "exp": expire.timestamp(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _verify_email_token(token: str, expected_type: str) -> str | None:
    """
    Internal helper — decode an email action token and return the email.

    Args:
        token:         Raw JWT string
        expected_type: Token type claim that must match

    Returns:
        Email string on success, ``None`` otherwise
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != expected_type:
            return None
        subject: str | None = payload.get("sub")
        return str(subject) if subject else None
    except jwt.PyJWTError:
        return None


# -- Password reset ----------------------------------------------------------


def create_password_reset_token(email: str) -> str:
    """
    Generate a password-reset token for *email*.

    Returns:
        Encoded JWT string
    """
    return _create_email_token(email, "password_reset")


def verify_password_reset_token(token: str) -> str | None:
    """
    Validate a password-reset token.

    Returns:
        Email on success, ``None`` otherwise
    """
    return _verify_email_token(token, "password_reset")


# -- New account verification ------------------------------------------------


def generate_new_account_token(email: str) -> str:
    """
    Generate an account-verification token for *email*.

    Returns:
        Encoded JWT string
    """
    return _create_email_token(email, "new_account")


def verify_new_account_token(token: str) -> str | None:
    """
    Validate a new-account verification token.

    Returns:
        Email on success, ``None`` otherwise
    """
    return _verify_email_token(token, "new_account")
