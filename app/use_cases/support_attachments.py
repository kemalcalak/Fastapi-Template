import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.models.file import File
from app.repositories.file import get_file


async def resolve_attachment_files(
    session: AsyncSession,
    *,
    file_ids: Sequence[uuid.UUID],
    uploader_id: uuid.UUID,
) -> list[File]:
    """Validate that each id refers to a file owned by ``uploader_id``.

    Returns the resolved ``File`` rows in request order. Raises 404 if any id
    is unknown and 403 if a file exists but was uploaded by someone else, so a
    caller can only attach files they uploaded themselves.
    """
    resolved: list[File] = []
    for file_id in file_ids:
        file = await get_file(session, file_id)
        if file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorMessages.ATTACHMENT_NOT_FOUND,
            )
        if file.uploaded_by_id != uploader_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ErrorMessages.ATTACHMENT_NOT_OWNED,
            )
        resolved.append(file)
    return resolved
