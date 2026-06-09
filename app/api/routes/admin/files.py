import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.decorators import audit_unexpected_failure
from app.api.deps import SessionDep, require_permission
from app.models.user import User
from app.schemas.admin import AdminFileListItem, AdminFileListResponse
from app.schemas.admin_permission import Permission
from app.schemas.msg import Message
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.file_service import (
    delete_file_admin_service,
    get_file_admin_service,
    list_files_admin_service,
)

router = APIRouter()

AdminFilesRead = Annotated[User, Depends(require_permission(Permission.FILES_READ))]
AdminFilesDelete = Annotated[User, Depends(require_permission(Permission.FILES_DELETE))]


@router.get("", response_model=AdminFileListResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.FILE,
    endpoint="/admin/files",
)
async def list_files(
    _request: Request,
    _admin: AdminFilesRead,
    session: SessionDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    content_type: Annotated[str | None, Query(max_length=100)] = None,
    uploader: Annotated[str | None, Query(max_length=255)] = None,
) -> AdminFileListResponse:
    """List uploaded files with admin-only filters and pagination.

    ``uploader`` does a case-insensitive match on the uploader's first name,
    last name, or email.
    """
    return await list_files_admin_service(
        session=session,
        skip=skip,
        limit=limit,
        content_type=content_type,
        uploader=uploader,
    )


@router.get("/{file_id}", response_model=AdminFileListItem)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.FILE,
    endpoint="/admin/files/{file_id}",
)
async def get_file(
    _request: Request,
    _admin: AdminFilesRead,
    session: SessionDep,
    file_id: uuid.UUID,
) -> AdminFileListItem:
    """Return the admin view of a single file."""
    return await get_file_admin_service(session=session, file_id=file_id)


@router.delete("/{file_id}", response_model=Message)
@audit_unexpected_failure(
    activity_type=ActivityType.DELETE,
    resource_type=ResourceType.FILE,
    endpoint="/admin/files/{file_id}",
)
async def delete_file(
    request: Request,
    current_user: AdminFilesDelete,
    session: SessionDep,
    file_id: uuid.UUID,
) -> Message:
    """Hard-delete a file (Cloudinary asset + DB row). Clears any avatar use."""
    return await delete_file_admin_service(
        request=request,
        session=session,
        current_user=current_user,
        file_id=file_id,
    )
