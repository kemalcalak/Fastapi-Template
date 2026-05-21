from fastapi import APIRouter, Request

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentSuperUser, SessionDep
from app.schemas.admin import AdminStats
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.admin.stats_service import get_admin_stats_service

router = APIRouter()


@router.get("/stats", response_model=AdminStats)
@audit_unexpected_failure(
    activity_type=ActivityType.READ,
    resource_type=ResourceType.USER,
    endpoint="/admin/stats",
)
async def get_stats(
    _request: Request,
    _admin: CurrentSuperUser,
    session: SessionDep,
) -> AdminStats:
    """Return aggregate dashboard counts in a single round-trip."""
    return await get_admin_stats_service(session=session)
