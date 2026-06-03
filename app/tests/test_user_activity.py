import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_activity import UserActivity
from app.repositories.user_activity import create_user_activity
from app.schemas.user_activity import (
    ActivityStatus,
    ActivityType,
    ResourceType,
    UserActivityCreate,
)

# Import the test session maker from conftest
from app.tests.conftest import TestingSessionLocal
from app.use_cases.log_activity import log_activity


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

    result = await db_session.execute(
        select(UserActivity).where(UserActivity.id == activity.id)
    )
    db_record = result.scalars().first()

    assert db_record is not None
    assert db_record.user_id == fake_user_id
    assert db_record.activity_type == ActivityType.LOGIN.value


@pytest.mark.asyncio
async def test_log_activity_defaults_success_status_code_to_200(
    db_session: AsyncSession,
):
    """log_activity should stamp successful entries with HTTP 200 by default."""
    user_id = uuid.uuid4()
    db_session.add(
        User(
            id=user_id,
            email="success_code@example.com",
            hashed_password="hashed_dummy_password",
            is_active=True,
        )
    )
    await db_session.commit()

    activity = await log_activity(
        session=db_session,
        user_id=user_id,
        activity_type=ActivityType.LOGIN,
        resource_type=ResourceType.AUTH,
    )

    assert activity.status == ActivityStatus.SUCCESS.value
    assert activity.status_code == 200


@pytest.mark.asyncio
async def test_log_activity_persists_failure_status_code(db_session: AsyncSession):
    """log_activity should persist the explicit status_code passed on failures."""
    user_id = uuid.uuid4()
    db_session.add(
        User(
            id=user_id,
            email="failure_code@example.com",
            hashed_password="hashed_dummy_password",
            is_active=True,
        )
    )
    await db_session.commit()

    activity = await log_activity(
        session=db_session,
        user_id=user_id,
        activity_type=ActivityType.LOGIN,
        resource_type=ResourceType.AUTH,
        status=ActivityStatus.FAILURE,
        status_code=401,
        details={"reason": "invalid_password"},
    )

    assert activity.status == ActivityStatus.FAILURE.value
    assert activity.status_code == 401
