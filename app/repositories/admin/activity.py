import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_activity import UserActivity
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType


def _apply_filters(
    stmt: Select,
    *,
    user_id: uuid.UUID | None,
    activity_type: ActivityType | None,
    resource_type: ResourceType | None,
    status: ActivityStatus | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select:
    """Attach admin activity-log filters to a base statement."""
    if user_id is not None:
        stmt = stmt.where(UserActivity.user_id == user_id)
    if activity_type is not None:
        stmt = stmt.where(UserActivity.activity_type == activity_type.value)
    if resource_type is not None:
        stmt = stmt.where(UserActivity.resource_type == resource_type.value)
    if status is not None:
        stmt = stmt.where(UserActivity.status == status.value)
    if date_from is not None:
        stmt = stmt.where(UserActivity.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(UserActivity.created_at <= date_to)
    return stmt


async def list_activities_admin(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    user_id: uuid.UUID | None = None,
    activity_type: ActivityType | None = None,
    resource_type: ResourceType | None = None,
    status: ActivityStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[Sequence[UserActivity], int]:
    """Return a filtered, paginated activity page plus the matching total count."""
    count_stmt = _apply_filters(
        select(func.count()).select_from(UserActivity),
        user_id=user_id,
        activity_type=activity_type,
        resource_type=resource_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    total = (await session.execute(count_stmt)).scalar_one()

    rows_stmt = _apply_filters(
        select(UserActivity),
        user_id=user_id,
        activity_type=activity_type,
        resource_type=resource_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    rows_stmt = (
        rows_stmt.order_by(UserActivity.created_at.desc()).offset(skip).limit(limit)
    )
    activities = (await session.execute(rows_stmt)).scalars().all()

    return activities, total
