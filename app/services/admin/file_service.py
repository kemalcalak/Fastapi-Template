import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.models.file import File
from app.models.user import User
from app.repositories.admin.file import get_file_admin, list_files_admin
from app.repositories.file import delete_file as delete_file_record
from app.schemas.admin import AdminFileListItem, AdminFileListResponse
from app.schemas.msg import Message
from app.schemas.user_activity import ActivityType, ResourceType
from app.use_cases.log_activity import log_activity


async def list_files_admin_service(
    session: AsyncSession,
    *,
    skip: int,
    limit: int,
    content_type: str | None,
    uploader: str | None,
) -> AdminFileListResponse:
    """Return the filtered, paginated admin file list."""
    files, total = await list_files_admin(
        session,
        skip=skip,
        limit=limit,
        content_type=content_type,
        uploader=uploader,
    )
    return AdminFileListResponse(
        data=[AdminFileListItem.model_validate(f) for f in files],
        total=total,
        skip=skip,
        limit=limit,
    )


async def _load_file(session: AsyncSession, file_id: uuid.UUID) -> File:
    """Fetch a file (with its uploader) for admin access or raise 404."""
    file = await get_file_admin(session, file_id)
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.FILE_NOT_FOUND,
        )
    return file


async def get_file_admin_service(
    session: AsyncSession, file_id: uuid.UUID
) -> AdminFileListItem:
    """Return a single file's admin view or raise 404."""
    file = await _load_file(session, file_id)
    return AdminFileListItem.model_validate(file)


async def delete_file_admin_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    file_id: uuid.UUID,
) -> Message:
    """Hard-delete a file: remove the Cloudinary asset and the DB row.

    If the file is currently a user's avatar, the ON DELETE SET NULL foreign
    key clears that reference automatically. The action is audit-logged.
    """
    file = await _load_file(session, file_id)

    public_id = file.public_id
    await storage.delete_file(public_id)
    await delete_file_record(session, file)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.DELETE,
        resource_type=ResourceType.FILE,
        resource_id=file_id,
        details={"action": "admin_deleted_file", "public_id": public_id},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.ADMIN_FILE_DELETED)
