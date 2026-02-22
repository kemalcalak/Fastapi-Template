import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.models.user import User
from app.utils import utc_now


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Get a single user by their UUID. Excludes deleted users."""
    user = await session.get(User, user_id)
    if user and user.is_deleted:
        return None
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Get a single user by their email address. Excludes deleted users."""
    statement = (
        select(User).where(User.email == email).where(User.is_deleted.is_(False))
    )
    result = await session.execute(statement)
    return result.scalars().first()


async def get_users_with_count(
    session: AsyncSession, skip: int = 0, limit: int = 100
) -> tuple[Sequence[User], int]:
    """Get paginated users and total count. Excludes deleted users."""
    count_statement = (
        select(func.count()).select_from(User).where(User.is_deleted.is_(False))
    )
    count_result = await session.execute(count_statement)
    count = count_result.scalar_one()

    users_statement = (
        select(User).where(User.is_deleted.is_(False)).offset(skip).limit(limit)
    )
    users_result = await session.execute(users_statement)
    users = users_result.scalars().all()
    return users, count


async def create_user(session: AsyncSession, user: User) -> User:
    """Create a new user in the database."""
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(session: AsyncSession, db_user: User, update_data: dict) -> User:
    """Update an existing user's data."""
    for key, value in update_data.items():
        setattr(db_user, key, value)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def soft_delete_user(session: AsyncSession, user: User) -> None:
    """Mark a user as deleted without physical removal."""
    user.is_deleted = True
    user.deleted_at = utc_now()
    user.is_active = False
    session.add(user)
    await session.commit()


async def delete_user(session: AsyncSession, db_user: User) -> None:
    """Delete a user from the database."""
    await session.delete(db_user)
    await session.commit()
