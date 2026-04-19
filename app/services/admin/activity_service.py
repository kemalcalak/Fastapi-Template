import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.repositories.admin.activity import list_activities_admin
from app.repositories.user import get_user_by_id
from app.schemas.admin import AdminActivityItem, AdminActivityListResponse
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType


async def list_activities_admin_service(
    session: AsyncSession,
    *,
    skip: int,
    limit: int,
    user_id: uuid.UUID | None,
    activity_type: ActivityType | None,
    resource_type: ResourceType | None,
    status_filter: ActivityStatus | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> AdminActivityListResponse:
    """Return a filtered, paginated activity log view for the admin panel."""
    activities, total = await list_activities_admin(
        session,
        skip=skip,
        limit=limit,
        user_id=user_id,
        activity_type=activity_type,
        resource_type=resource_type,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
    return AdminActivityListResponse(
        data=[AdminActivityItem.model_validate(a) for a in activities],
        total=total,
        skip=skip,
        limit=limit,
    )


async def list_user_activities_admin_service(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    skip: int,
    limit: int,
) -> AdminActivityListResponse:
    """Return the activity log for a single user (admin drill-down view)."""
    target = await get_user_by_id(session, user_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )

    activities, total = await list_activities_admin(
        session, skip=skip, limit=limit, user_id=user_id
    )
    return AdminActivityListResponse(
        data=[AdminActivityItem.model_validate(a) for a in activities],
        total=total,
        skip=skip,
        limit=limit,
    )
