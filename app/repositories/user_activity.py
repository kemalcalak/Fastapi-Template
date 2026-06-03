from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_activity import UserActivity
from app.schemas.user_activity import UserActivityCreate


async def create_user_activity(
    session: AsyncSession, activity_data: UserActivityCreate
) -> UserActivity:
    """Create a new user activity log in the database."""
    db_activity = UserActivity(
        user_id=activity_data.user_id,
        activity_type=activity_data.activity_type.value,
        resource_type=activity_data.resource_type.value,
        resource_id=activity_data.resource_id,
        details=activity_data.details,
        status=activity_data.status.value,
        status_code=activity_data.status_code,
        ip_address=activity_data.ip_address,
        user_agent=activity_data.user_agent,
    )
    session.add(db_activity)
    await session.commit()
    await session.refresh(db_activity)
    return db_activity
