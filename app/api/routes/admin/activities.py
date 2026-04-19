import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentSuperUser, SessionDep
from app.schemas.admin import AdminActivityListResponse
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType
from app.services.admin.activity_service import (
    list_activities_admin_service,
    list_user_activities_admin_service,
)

router = APIRouter()


@router.get("/users/{user_id}/activities", response_model=AdminActivityListResponse)
async def list_user_activities(
    _admin: CurrentSuperUser,
    session: SessionDep,
    user_id: uuid.UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminActivityListResponse:
    """Return the activity log for a specific user."""
    return await list_user_activities_admin_service(
        session=session,
        user_id=user_id,
        skip=skip,
        limit=limit,
    )


@router.get("/activities", response_model=AdminActivityListResponse)
async def list_activities(
    _admin: CurrentSuperUser,
    session: SessionDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    user_id: uuid.UUID | None = None,
    activity_type: ActivityType | None = None,
    resource_type: ResourceType | None = None,
    status_filter: Annotated[ActivityStatus | None, Query(alias="status")] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> AdminActivityListResponse:
    """Return the global activity log with filters and pagination."""
    return await list_activities_admin_service(
        session=session,
        skip=skip,
        limit=limit,
        user_id=user_id,
        activity_type=activity_type,
        resource_type=resource_type,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
