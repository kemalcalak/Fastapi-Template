from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token_blacklist import TokenBlacklist


async def add_token_to_blacklist(session: AsyncSession, token: str) -> TokenBlacklist:
    """Add a token to the blacklist."""
    blacklisted_token = TokenBlacklist(token=token)
    session.add(blacklisted_token)
    await session.commit()
    await session.refresh(blacklisted_token)
    return blacklisted_token


async def is_token_blacklisted(session: AsyncSession, token: str) -> bool:
    """Check if a token exists in the blacklist."""
    statement = select(TokenBlacklist).where(TokenBlacklist.token == token)
    result = await session.execute(statement)
    return result.scalars().first() is not None
