import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.models.file import File
from app.repositories.file import get_file
from app.schemas.file import FileCategory


async def resolve_attachment_files(
    session: AsyncSession,
    *,
    file_ids: Sequence[uuid.UUID],
    uploader_id: uuid.UUID,
    expected_category: FileCategory | None = None,
) -> list[File]:
    """Validate that each id refers to a file owned by ``uploader_id``.

    Returns the resolved ``File`` rows in request order. Raises 404 if any id is
    unknown, 403 if a file was uploaded by someone else, and 422 if
    ``expected_category`` is given and a file is in the wrong bucket — so support
    threads can only carry files uploaded as support attachments.
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
        if expected_category is not None and file.category != expected_category.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=ErrorMessages.ATTACHMENT_WRONG_CATEGORY,
            )
        resolved.append(file)
    return resolved
