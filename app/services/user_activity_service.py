import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_activity import UserActivity
from app.repositories.user_activity import create_user_activity
from app.schemas.common import ActivityDetails
from app.schemas.user_activity import (
    ActivityStatus,
    ActivityType,
    ResourceType,
    UserActivityCreate,
)


async def log_activity(
    session: AsyncSession,
    user_id: uuid.UUID,
    activity_type: ActivityType,
    resource_type: ResourceType,
    details: ActivityDetails | None = None,
    resource_id: uuid.UUID | None = None,
    status: ActivityStatus = ActivityStatus.SUCCESS,
    request: Request | None = None,
) -> UserActivity:
    """
    Service to log user activity.
    Automatically extracts IP address and User-Agent from the request if provided.
    """
    ip_address = None
    user_agent = None

    if request:
        if request.client:
            ip_address = request.client.host
        user_agent = request.headers.get("user-agent")

    activity_data = UserActivityCreate(
        user_id=user_id,
        activity_type=activity_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        status=status,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return await create_user_activity(session, activity_data)
