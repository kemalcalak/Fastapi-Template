import logging

from fastapi import HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import settings
from app.core.messages.error_message import ErrorMessages
from app.models.file import File
from app.models.user import User
from app.repositories.file import create_file
from app.schemas.user_activity import ActivityType, ResourceType
from app.use_cases.log_activity import log_activity

logger = logging.getLogger(__name__)

# /upload currently serves images only (the avatar use case). Broaden this set
# when another consumer (gallery, attachments, ...) needs other types.
ALLOWED_IMAGE_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)


async def upload_file_service(
    request: Request,
    session: AsyncSession,
    current_user: User,
    upload: UploadFile,
) -> File:
    """Validate an uploaded image, store it on Cloudinary, and persist metadata.

    Rejects files over ``MAX_UPLOAD_SIZE_BYTES`` (413) or whose content type is
    not an allowed image (415). The stored record is owned by ``current_user``
    and the upload is recorded in the activity log.
    """
    # Fast reject using the reported size before reading the body into memory.
    if upload.size is not None and upload.size > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=ErrorMessages.FILE_TOO_LARGE,
        )

    content_type = upload.content_type or ""
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=ErrorMessages.INVALID_FILE_TYPE,
        )

    content = await upload.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorMessages.FILE_EMPTY,
        )
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=ErrorMessages.FILE_TOO_LARGE,
        )

    try:
        result = await storage.upload_file(content, resource_type="image")
    except RuntimeError as e:
        # Missing/invalid Cloudinary credentials — a server misconfiguration.
        logger.error(f"Cloudinary not configured: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorMessages.INTERNAL_SERVER_ERROR,
        )
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ErrorMessages.FILE_UPLOAD_FAILED,
        )

    file = File(
        url=result.url,
        public_id=result.public_id,
        filename=upload.filename,
        content_type=content_type,
        size=len(content),
        uploaded_by_id=current_user.id,
    )
    created = await create_file(session, file)

    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.CREATE,
        resource_type=ResourceType.FILE,
        resource_id=created.id,
        details={"filename": created.filename, "size": created.size},
        request=request,
    )

    return created
