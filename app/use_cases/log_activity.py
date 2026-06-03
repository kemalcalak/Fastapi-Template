import uuid

from fastapi import Request
from fastapi import status as http_status
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
    status_code: int | None = None,
    request: Request | None = None,
) -> UserActivity:
    """Record an audit entry, extracting IP and user-agent from the request.

    ``status_code`` is the HTTP status code tied to the activity. When omitted
    it defaults to ``200`` for successful entries; failures should pass the
    code that was raised so it can be filtered on later.
    """
    if status_code is None and status == ActivityStatus.SUCCESS:
        status_code = http_status.HTTP_200_OK

    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    activity_data = UserActivityCreate(
        user_id=user_id,
        activity_type=activity_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        status=status,
        status_code=status_code,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return await create_user_activity(session, activity_data)
