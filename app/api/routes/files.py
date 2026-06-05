from typing import Annotated

from fastapi import APIRouter, Form, Request, UploadFile, status

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentActiveUser, SessionDep
from app.core.rate_limit import rate_limit_strict
from app.schemas.file import FileCategory, FilePublic
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.file_service import upload_file_service

router = APIRouter()


@router.post("/upload", response_model=FilePublic, status_code=status.HTTP_201_CREATED)
@rate_limit_strict("20/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.CREATE,
    resource_type=ResourceType.FILE,
    endpoint="/upload",
)
async def upload_file(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    file: UploadFile,
    category: Annotated[FileCategory, Form()] = FileCategory.GENERAL,
) -> FilePublic:
    """Upload an image and return its stored metadata.

    The file is stored on Cloudinary under ``<category>/<user_id>`` and owned by
    the authenticated caller. ``category`` defaults to ``general``; pass
    ``user_profile_photo`` or ``support_attachment`` to bucket the file. Attach
    it to a resource (e.g. an avatar) in a separate update call.
    """
    created = await upload_file_service(
        request=request,
        session=session,
        current_user=current_user,
        upload=file,
        category=category,
    )
    return FilePublic.model_validate(created)
