from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.decorators import audit_unexpected_failure
from app.api.deps import SessionDep, require_permission
from app.models.user import User
from app.schemas.admin import AdminStats
from app.schemas.admin_permission import Permission
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.stats_service import get_admin_stats_service

router = APIRouter()

AdminStatsRead = Annotated[User, Depends(require_permission(Permission.STATS_READ))]


@router.get("/stats", response_model=AdminStats)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.USER,
    endpoint="/admin/stats",
)
async def get_stats(
    _request: Request,
    _admin: AdminStatsRead,
    session: SessionDep,
) -> AdminStats:
    """Return aggregate dashboard counts in a single round-trip."""
    return await get_admin_stats_service(session=session)
