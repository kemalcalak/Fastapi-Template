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
DISPOSABLE_CACHE_TTL = 86400  # 24 hours
_DISPOSABLE_LOCK = asyncio.Lock()


def _get_domain(email: str) -> str | None:
    parts = email.rsplit("@", 1)
    return parts[1].lower() if len(parts) == 2 else None


async def check_mx_record(email: str) -> bool:
    """
    Check if the domain of the email has valid MX records.
    Returns True if valid, False if not.
    """
    try:
        domain = _get_domain(email)
        if domain is None:
            return False

        def _resolve_mx() -> int:
            records = dns.resolver.resolve(domain, "MX")
            return len(records)

        # Run the synchronous DNS query in a separate thread
        count = await asyncio.to_thread(_resolve_mx)
        return count > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, Exception) as e:
        logger.warning(f"MX record check failed for {email}: {e}")
        return False


async def is_disposable_email(email: str) -> bool:
    """
    Check if the email domain belongs to a disposable email provider via Redis cache.
    Returns True if it's disposable, False otherwise.
    """
    try:
        domain = _get_domain(email)
        if domain is None:
            return False

        async with _DISPOSABLE_LOCK:
            # Check if domain exists in the Redis set
            is_member = await redis_client.sismember(DISPOSABLE_CACHE_KEY, domain)

            if not is_member and not await redis_client.exists(DISPOSABLE_CACHE_KEY):
                # The key doesn't exist, we likely need to fetch the list
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf",
                        timeout=5.0,
                    )
                    if response.status_code == 200:
                        domains_list = response.text.strip().split("\n")
                        if domains_list:
                            # Add all domains to the Redis set
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
    except Exception as e:
        logger.error(f"Error checking disposable email for {email}: {e}")
        # If Redis or network error, fail open
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
