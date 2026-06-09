"""Startup data bootstrap: guarantees the system always has a superadmin."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.security import aget_password_hash
from app.models.user import User
from app.repositories.admin.user import (
    get_earliest_superadmin,
    root_superadmin_exists,
    superadmin_exists,
)
from app.repositories.user import create_user, get_user_by_email, update_user
from app.schemas.user import SystemRole

logger = logging.getLogger(__name__)


async def _ensure_root_designated(session: AsyncSession) -> None:
    """Backfill a root flag for older deployments that predate the column.

    A database may already hold one or more superadmins but none flagged as the
    root (e.g. seeded before this feature shipped). The oldest superadmin is
    promoted to root so the superadmin-tier actions always have an owner.
    """
    if await root_superadmin_exists(session):
        return
    earliest = await get_earliest_superadmin(session)
    if earliest is not None:
        await update_user(session, earliest, {"is_root_superadmin": True})
        logger.info("Designated %s as root superadmin", earliest.email)


async def ensure_first_superadmin() -> None:
    """Guarantee a root superadmin exists, seeding one from settings if none does.

    Idempotent and safe to run on every startup: if any superadmin is already
    present it only backfills the root flag when missing. Otherwise it promotes
    an existing account matching ``FIRST_SUPERUSER`` to root superadmin, or
    creates a fresh verified root superadmin from ``FIRST_SUPERUSER`` /
    ``FIRST_SUPERUSER_PASSWORD``.
    """
    async with AsyncSessionLocal() as session:
        if await superadmin_exists(session):
            await _ensure_root_designated(session)
            return

        existing = await get_user_by_email(session, settings.FIRST_SUPERUSER)
        if existing is not None:
            await update_user(
                session,
                existing,
                {
                    "role": SystemRole.SUPERADMIN.value,
                    "is_root_superadmin": True,
                },
            )
            logger.info(
                "Promoted existing user %s to root superadmin",
                settings.FIRST_SUPERUSER,
            )
            return

        hashed_password = await aget_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
        superadmin = User(
            email=settings.FIRST_SUPERUSER,
            hashed_password=hashed_password,
            role=SystemRole.SUPERADMIN.value,
            is_active=True,
            is_verified=True,
            is_root_superadmin=True,
        )
        await create_user(session, superadmin)
        logger.info("Seeded first root superadmin %s", settings.FIRST_SUPERUSER)
