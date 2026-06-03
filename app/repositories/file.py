import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File


async def create_file(session: AsyncSession, file: File) -> File:
    """Persist a new file record."""
    session.add(file)
    await session.commit()
    await session.refresh(file)
    return file


async def get_file(session: AsyncSession, file_id: uuid.UUID) -> File | None:
    """Get a single file by its UUID."""
    return await session.get(File, file_id)


async def delete_file(session: AsyncSession, file: File) -> None:
    """Permanently remove a file record."""
    await session.delete(file)
    await session.commit()
