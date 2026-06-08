"""Startup data bootstrap: guarantees the system always has a superadmin."""

import logging

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.security import aget_password_hash
from app.models.user import User
from app.repositories.admin.user import superadmin_exists
from app.repositories.user import create_user, get_user_by_email, update_user
from app.schemas.user import SystemRole

logger = logging.getLogger(__name__)


async def ensure_first_superadmin() -> None:
    """Guarantee a superadmin exists, seeding one from settings if none does.

    Idempotent and safe to run on every startup: if any superadmin is already
    present it returns immediately. Otherwise it promotes an existing account
    matching ``FIRST_SUPERUSER`` to superadmin, or creates a fresh verified
    superadmin from ``FIRST_SUPERUSER`` / ``FIRST_SUPERUSER_PASSWORD``.
    """
    async with AsyncSessionLocal() as session:
        if await superadmin_exists(session):
            return

        existing = await get_user_by_email(session, settings.FIRST_SUPERUSER)
        if existing is not None:
            await update_user(session, existing, {"role": SystemRole.SUPERADMIN.value})
            logger.info(
                "Promoted existing user %s to superadmin", settings.FIRST_SUPERUSER
            )
            return

        hashed_password = await aget_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
        superadmin = User(
            email=settings.FIRST_SUPERUSER,
            hashed_password=hashed_password,
            role=SystemRole.SUPERADMIN.value,
            is_active=True,
            is_verified=True,
        )
        await create_user(session, superadmin)
        logger.info("Seeded first superadmin %s", settings.FIRST_SUPERUSER)
