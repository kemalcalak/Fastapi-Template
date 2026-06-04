"""Seed verified, active accounts for load testing.

The login endpoint rejects unverified accounts, so load-test users cannot be
created through the public /auth/register flow (which requires email
verification). This script inserts them straight into the database with
is_verified=True and is_active=True.

Run from the host while the database port is published (docker-compose up -d db):

    uv run python -m loadtest.seed_users

Configure with the same environment variables the locustfile reads:
    LT_USER_COUNT (default 50), LT_EMAIL_PREFIX, LT_EMAIL_DOMAIN, LT_PASSWORD.

The script is idempotent: accounts whose email already exists are skipped.
"""

import asyncio
import os

from app.core.db import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User
from app.repositories.user import create_user, get_user_by_email

EMAIL_PREFIX = os.getenv("LT_EMAIL_PREFIX", "loadtest+")
EMAIL_DOMAIN = os.getenv("LT_EMAIL_DOMAIN", "example.com")
PASSWORD = os.getenv("LT_PASSWORD", "LoadTest123!")
USER_COUNT = int(os.getenv("LT_USER_COUNT", "50"))


async def seed() -> None:
    """Create USER_COUNT load-test accounts, skipping any that already exist."""
    hashed_password = get_password_hash(PASSWORD)
    created = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        for index in range(USER_COUNT):
            email = f"{EMAIL_PREFIX}{index}@{EMAIL_DOMAIN}"
            if await get_user_by_email(session, email) is not None:
                skipped += 1
                continue

            user = User(
                email=email,
                hashed_password=hashed_password,
                is_active=True,
                is_verified=True,
                role="user",
                first_name="Load",
                last_name=f"Test{index}",
            )
            await create_user(session, user)
            created += 1

    print(f"Seed complete: {created} created, {skipped} already existed.")


if __name__ == "__main__":
    asyncio.run(seed())
