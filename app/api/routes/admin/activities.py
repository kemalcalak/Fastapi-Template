import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentAdminUser, SessionDep
from app.schemas.admin import AdminActivityFilter, AdminActivityListResponse
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.activity_service import (
    list_activities_admin_service,
    list_user_activities_admin_service,
)

router = APIRouter()


@router.get("/users/{user_id}/activities", response_model=AdminActivityListResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.ACTIVITY,
    endpoint="/admin/users/{user_id}/activities",
)
async def list_user_activities(
    _request: Request,
    _admin: CurrentAdminUser,
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


@router.post("/activities/search", response_model=AdminActivityListResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.ACTIVITY,
    endpoint="/admin/activities/search",
)
async def search_activities(
    _request: Request,
    _admin: CurrentAdminUser,
    session: SessionDep,
    filters: AdminActivityFilter,
) -> AdminActivityListResponse:
    """Return the global activity log; filters + pagination ride the POST body."""
    return await list_activities_admin_service(
        session=session,
        skip=filters.skip,
        limit=filters.limit,
        user_id=filters.user_id,
        user_search=filters.user_search,
        activity_type=filters.activity_type,
        resource_type=filters.resource_type,
        status_filter=filters.status,
        status_code=filters.status_code,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )
