import asyncio
import logging
import smtplib
from email.message import EmailMessage

import dns.resolver
import httpx
import redis.asyncio as aioredis  # type: ignore

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cache for disposable domains using Redis
redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
DISPOSABLE_CACHE_KEY = "disposable_domains_cache"
DISPOSABLE_CACHE_TTL = settings.DISPOSABLE_EMAIL_CACHE_TTL_SECONDS
_DISPOSABLE_LOCK = asyncio.Lock()


def _get_domain(email: str) -> str | None:
    """Return the lowercase domain part of ``email`` or ``None`` if malformed."""
    parts = email.rsplit("@", 1)
    return parts[1].lower() if len(parts) == 2 else None


async def check_mx_record(email: str) -> bool:
    """Return True when the email domain publishes at least one MX record.

    The DNS lookup is intentionally forgiving — any resolver error is
    treated as "no valid MX" rather than propagated, so a transient
    network blip cannot block registration for every caller.
    """
    domain = _get_domain(email)
    if domain is None:
        return False

    def _resolve_mx() -> int:
        """Resolve MX records synchronously; runs inside ``asyncio.to_thread``."""
        records = dns.resolver.resolve(domain, "MX")
        return len(records)

    try:
        count = await asyncio.to_thread(_resolve_mx)
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.resolver.LifetimeTimeout,
        dns.exception.DNSException,
    ) as e:
        logger.warning(f"MX record check failed for {email}: {e}")
        return False
    return count > 0


async def is_disposable_email(email: str) -> bool:
    """Return True when the email domain matches a known disposable provider.

    Uses a Redis set seeded from an upstream blocklist (lazy fetch on first
    miss). Any Redis / network error falls open (treated as non-disposable)
    so an outage cannot lock legitimate users out of registration.
    """
    domain = _get_domain(email)
    if domain is None:
        return False

    try:
        async with _DISPOSABLE_LOCK:
            is_member = await redis_client.sismember(DISPOSABLE_CACHE_KEY, domain)

            if not is_member and not await redis_client.exists(DISPOSABLE_CACHE_KEY):
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        settings.DISPOSABLE_EMAIL_LIST_URL,
                        timeout=5.0,
                    )
                if response.status_code == 200:
                    domains_list = response.text.strip().split("\n")
                    if domains_list:
                        await redis_client.sadd(DISPOSABLE_CACHE_KEY, *domains_list)
                        await redis_client.expire(
                            DISPOSABLE_CACHE_KEY, DISPOSABLE_CACHE_TTL
                        )
                        is_member = domain in domains_list
                else:
                    logger.warning(
                        f"Failed to fetch disposable domains, status code: {response.status_code}"
                    )

        return bool(is_member)
    except (aioredis.RedisError, httpx.HTTPError) as e:
        logger.error(f"Error checking disposable email for {email}: {e}")
        return False


async def send_email(
    to: str,
    subject: str,
    body: str,
    plain_text: str,
    user_id: str | None = None,
    is_html: bool = True,
) -> bool:
    """
    Send an email via configured SMTP server.
    Configures properly bounce handler addresses via the envelope_from.
    """
    if not settings.SMTP_HOST:
        logger.warning("SMTP_HOST not set. Email will not be sent.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAILS_FROM_EMAIL
    msg["To"] = to

    domain = (
        settings.EMAILS_FROM_EMAIL.split("@")[-1]
        if "@" in settings.EMAILS_FROM_EMAIL
        else "example.com"
    )
    envelope_from = (
        f"bounce+{user_id}@{domain}" if user_id else settings.EMAILS_FROM_EMAIL
    )

    if user_id:
        msg["X-User-ID"] = str(user_id)

    if is_html:
        msg.set_content(plain_text)
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(plain_text)

    def _send_sync() -> None:
        smtp_class = smtplib.SMTP_SSL if settings.SMTP_USE_SSL else smtplib.SMTP
        with smtp_class(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if not settings.SMTP_USE_SSL:
                smtp.ehlo()
                if settings.SMTP_USE_STARTTLS:
                    # STARTTLS is strictly enforced. Will raise SMTPNotSupportedError if not supported by the server.
                    smtp.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg, from_addr=envelope_from)

    try:
        await asyncio.to_thread(_send_sync)
        logger.info(f"Successfully sent email to {to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False
