import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from app.models.user import User
from app.models.user_activity import UserActivity
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType


def _filtered_activities_stmt(
    *,
    user_id: uuid.UUID | None,
    user_search: str | None,
    activity_type: ActivityType | None,
    resource_type: ResourceType | None,
    status: ActivityStatus | None,
    status_code: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select:
    """Build the filtered base statement shared by count and list queries."""
    stmt = select(UserActivity)
    if user_id is not None:
        stmt = stmt.where(UserActivity.user_id == user_id)
    if user_search:
        # Match the acting user by name/email. ILIKE on raw columns so the
        # pg_trgm indexes on email/first_name/last_name can serve the query.
        like = f"%{user_search}%"
        stmt = stmt.join(User, UserActivity.user_id == User.id).where(
            or_(
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            )
        )
    if activity_type is not None:
        stmt = stmt.where(UserActivity.activity_type == activity_type.value)
    if resource_type is not None:
        stmt = stmt.where(UserActivity.resource_type == resource_type.value)
    if status is not None:
        stmt = stmt.where(UserActivity.status == status.value)
    if status_code is not None:
        stmt = stmt.where(UserActivity.status_code == status_code)
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
    user_search: str | None = None,
    activity_type: ActivityType | None = None,
    resource_type: ResourceType | None = None,
    status: ActivityStatus | None = None,
    status_code: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[Sequence[UserActivity], int]:
    """Return a filtered, paginated activity page plus the matching total count."""
    base_stmt = _filtered_activities_stmt(
        user_id=user_id,
        user_search=user_search,
        activity_type=activity_type,
        resource_type=resource_type,
        status=status,
        status_code=status_code,
        date_from=date_from,
        date_to=date_to,
    )

    count_stmt = base_stmt.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = (await session.execute(count_stmt)).scalar_one()

    rows_stmt = (
        base_stmt.options(selectinload(UserActivity.user))
        .order_by(UserActivity.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    activities = (await session.execute(rows_stmt)).scalars().all()

    return activities, total
