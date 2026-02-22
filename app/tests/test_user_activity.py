import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Import the test session maker from conftest
from app.tests.conftest import TestingSessionLocal
from app.repositories.user_activity import create_user_activity
from app.repositories.user import create_user
from app.models.user import User
from app.schemas.user_activity import (
    UserActivityCreate,
    ActivityType,
    ResourceType,
    ActivityStatus,
)
from app.models.user_activity import UserActivity


@pytest.fixture
async def db_session() -> AsyncSession:
    """Fixture that provides a fresh database session for a test."""
    async with TestingSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_create_user_activity(db_session: AsyncSession):
    """
    Test that a UserActivity can be successfully created and stored in the database.
    This doesn't use the API, but tests the underlying persistence and schemas directly.
    """
    # 1. First, we need a user in the database to link the activity to.
    fake_user_id = uuid.uuid4()
    test_user = User(
        id=fake_user_id,
        email="activity_test@example.com",
        hashed_password="hashed_dummy_password",
        is_active=True,
    )
    db_session.add(test_user)
    await db_session.commit()

    # 2. Prepare the activity data
    resource_id = uuid.uuid4()
    activity_data = UserActivityCreate(
        user_id=fake_user_id,
        activity_type=ActivityType.LOGIN,
        resource_type=ResourceType.AUTH,
        resource_id=resource_id,
        details={"ip": "127.0.0.1", "device": "Desktop"},
        status=ActivityStatus.SUCCESS,
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0",
    )

    # 3. Call the repository logic to create the activity
    activity = await create_user_activity(db_session, activity_data=activity_data)

    # 4. Verify it was created successfully and returned
    assert activity.id is not None
    assert activity.user_id == fake_user_id
    assert activity.activity_type == ActivityType.LOGIN.value
    assert activity.resource_type == ResourceType.AUTH.value
    assert activity.resource_id == resource_id
    assert activity.details == {"ip": "127.0.0.1", "device": "Desktop"}
    assert activity.status == ActivityStatus.SUCCESS.value
    assert activity.ip_address == "127.0.0.1"

    # 5. Make sure we can retrieve it from the database directly using SQLAlchemy (ORM)
    from sqlalchemy import select
    result = await db_session.execute(select(UserActivity).where(UserActivity.id == activity.id))
    db_record = result.scalars().first()

    assert db_record is not None
    assert db_record.user_id == fake_user_id
    assert db_record.activity_type == ActivityType.LOGIN.value
