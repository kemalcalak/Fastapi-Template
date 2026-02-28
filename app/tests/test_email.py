import smtplib
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import Response

from app.core.config import settings
from app.core.email import (
    check_mx_record,
    is_disposable_email,
    send_email,
)


@pytest.fixture(autouse=True)
async def reset_disposable_cache():
    """Reset global disposable cache state before each test"""
    # Simply flush the redis mock if we're using one,
    # but here we'll just mock the redis client directly per test
    yield
    # No global vars to reset anymore


@pytest.mark.asyncio
async def test_check_mx_record_valid():
    with patch("dns.resolver.resolve") as mock_resolve:
        # Mocking dns.resolver.resolve to return a non-empty list
        mock_resolve.return_value = ["dummy_mx_record"]
        result = await check_mx_record("test@google.com")
        assert result is True


@pytest.mark.asyncio
async def test_check_mx_record_invalid():
    with patch("dns.resolver.resolve") as mock_resolve:
        # Mocking dns.resolver.resolve to raise an exception
        import dns.resolver

        mock_resolve.side_effect = dns.resolver.NXDOMAIN
        result = await check_mx_record("test@invalid.domain.that.doesnt.exist")
        assert result is False


@pytest.mark.asyncio
async def test_is_disposable_email_true_from_api():
    # Mocking httpx.AsyncClient.get for disposable list retrieval
    mock_response = Response(status_code=200, content=b"tempmail.com\nmailinator.com\n")

    with patch("app.core.email.redis_client") as mock_redis:
        mock_redis.sismember = AsyncMock(return_value=False)
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.sadd = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await is_disposable_email("user@tempmail.com")
            assert result is True


@pytest.mark.asyncio
async def test_is_disposable_email_true_from_cache():
    with patch("app.core.email.redis_client") as mock_redis:
        mock_redis.sismember = AsyncMock(return_value=True)

        result = await is_disposable_email("user@tempmail.com")
        assert result is True


@pytest.mark.asyncio
async def test_is_disposable_email_false():
    mock_response = Response(status_code=200, content=b"tempmail.com\nmailinator.com\n")

    with patch("app.core.email.redis_client") as mock_redis:
        mock_redis.sismember = AsyncMock(return_value=False)
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.sadd = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await is_disposable_email("user@gmail.com")
            assert result is False


@pytest.mark.asyncio
async def test_is_disposable_email_fetch_error():
    # In case the blocklist URL fails to load, it should fail open (return False)
    mock_response = Response(status_code=500, content=b"Internal Server Error")
    mock_response.raise_for_status = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Error", request=AsyncMock(), response=mock_response
        )
    )

    with patch("app.core.email.redis_client") as mock_redis:
        mock_redis.sismember = AsyncMock(return_value=False)
        mock_redis.exists = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await is_disposable_email("user@tempmail.com")
            assert result is False


@pytest.mark.asyncio
async def test_send_email_success():
    # Setup SMTP configurations for testing
    settings.SMTP_HOST = "localhost"
    settings.SMTP_PORT = 1025
    settings.SMTP_USER = "user"
    settings.SMTP_PASSWORD = "password"
    settings.EMAILS_FROM_EMAIL = "noreply@example.com"
    settings.SMTP_USE_STARTTLS = True  # Ensures STARTTLS is called
    settings.SMTP_USE_SSL = False

    with patch("smtplib.SMTP") as mock_smtp_class:
        # Mock the SMTP instance and context manager
        mock_smtp_instance = mock_smtp_class.return_value.__enter__.return_value

        result = await send_email(
            to="test@example.com",
            subject="Test Subject",
            body="Test Body",
            plain_text="Test Body Plain",
            user_id="123",
        )

        assert result is True
        mock_smtp_class.assert_called_with(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=15
        )
        mock_smtp_instance.ehlo.assert_called()
        mock_smtp_instance.starttls.assert_called()
        mock_smtp_instance.login.assert_called_with(
            settings.SMTP_USER, settings.SMTP_PASSWORD
        )
        mock_smtp_instance.send_message.assert_called()


@pytest.mark.asyncio
async def test_send_email_ssl_success():
    # Setup SMTP SSL configurations for testing
    settings.SMTP_HOST = "localhost"
    settings.SMTP_PORT = 465
    settings.SMTP_USER = "user"
    settings.SMTP_PASSWORD = "password"
    settings.EMAILS_FROM_EMAIL = "noreply@example.com"
    settings.SMTP_USE_STARTTLS = False
    settings.SMTP_USE_SSL = True

    with patch("smtplib.SMTP_SSL") as mock_smtp_class:
        # Mock the SMTP_SSL instance and context manager
        mock_smtp_instance = mock_smtp_class.return_value.__enter__.return_value

        result = await send_email(
            to="test@example.com",
            subject="Test Subject",
            body="Test Body",
            plain_text="Test Body Plain",
            user_id="123",
        )

        assert result is True
        mock_smtp_class.assert_called_with(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=15
        )
        # ehlo and starttls should NOT be called for SMTP_SSL in our implementation
        mock_smtp_instance.ehlo.assert_not_called()
        mock_smtp_instance.starttls.assert_not_called()
        mock_smtp_instance.login.assert_called_with(
            settings.SMTP_USER, settings.SMTP_PASSWORD
        )
        mock_smtp_instance.send_message.assert_called()


@pytest.mark.asyncio
async def test_send_email_failure():
    settings.SMTP_HOST = "localhost"
    settings.SMTP_USE_SSL = False

    with patch("smtplib.SMTP") as mock_smtp_class:
        # Simulate network or login failure
        mock_smtp_instance = mock_smtp_class.return_value.__enter__.return_value
        mock_smtp_instance.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Authentication failed"
        )

        result = await send_email(
            to="test@example.com",
            subject="Test Subject",
            body="Test Body",
            plain_text="Test Body Plain",
        )

        assert result is False
