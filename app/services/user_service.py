import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messages.error_message import ErrorMessages
from app.core.messages.success_message import SuccessMessages
from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.repositories.user import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_users_with_count,
    soft_delete_user,
    update_user,
)
from app.schemas.msg import Message
from app.schemas.user import UserCreate, UsersPublic, UserUpdate, UserUpdateMe
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.user_activity_service import log_activity


async def delete_own_account_service(
    request: Request, session: AsyncSession, current_user: User, password: str
) -> Message:
    """
    Securely delete own account with password confirmation.
    Uses soft delete.
    """
    if not verify_password(password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorMessages.INVALID_PASSWORD,
        )
    await soft_delete_user(session, current_user)
    
    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.DELETE,
        resource_type=ResourceType.USER,
        resource_id=current_user.id,
        details={"deleted_by": "self"},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.USER_DELETED)


async def delete_user_service(
    request: Request, session: AsyncSession, current_user: User, user_id: uuid.UUID
) -> Message:
    """Admin-level soft delete for any user."""
    db_user = await get_user_service(session, user_id)
    await soft_delete_user(session, db_user)
    
    await log_activity(
        session=session,
        user_id=current_user.id,
        activity_type=ActivityType.DELETE,
        resource_type=ResourceType.USER,
        resource_id=db_user.id,
        details={"deleted_user_email": db_user.email},
        request=request,
    )

    return Message(success=True, message=SuccessMessages.USER_DELETED)


async def create_user_service(
    request: Request | None, session: AsyncSession, user_create: UserCreate, current_user: User | None = None
) -> User:
    """
    Business logic to create a new user.
    Checks for email availability and hashes the password.
    """
    # 1. Guard check: Email must be unique
    existing_user = await get_user_by_email(session, email=user_create.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorMessages.EMAIL_ALREADY_EXISTS,
        )

    # 2. Prepare user object
    user_data = user_create.model_dump(exclude={"password"})
    db_obj = User(
        **user_data,
        hashed_password=get_password_hash(user_create.password)
    )

    # 3. Call repository
    created_user = await create_user(session, db_obj)
    
    if current_user and request:
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.CREATE,
            resource_type=ResourceType.USER,
            resource_id=created_user.id,
            details={"email": created_user.email},
            request=request,
        )
        
    return created_user


async def get_user_service(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Get a user by ID or raise 404."""
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorMessages.USER_NOT_FOUND,
        )
    return user


async def list_users_service(
    session: AsyncSession, skip: int = 0, limit: int = 100
) -> UsersPublic:
    """List users with pagination count."""
    users, count = await get_users_with_count(session, skip=skip, limit=limit)
    return UsersPublic(data=users, count=count)


async def update_user_service(
    request: Request, session: AsyncSession, current_user: User, user_id: uuid.UUID, user_update: UserUpdate | UserUpdateMe
) -> User:
    """Update user information including password hashing if provided."""
    db_user = await get_user_service(session, user_id)

    # 1. Check email uniqueness if email is being updated
    if user_update.email and user_update.email != db_user.email:
        existing_user = await get_user_by_email(session, email=user_update.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorMessages.EMAIL_ALREADY_EXISTS,
            )

    # 2. Prepare update data
    update_dict = user_update.model_dump(exclude_unset=True)
    if "password" in update_dict:
        password = update_dict.pop("password")
        update_dict["hashed_password"] = get_password_hash(password)

    # 3. Call repository
    updated_user = await update_user(session, db_user, update_dict)
    
    await log_activity(
        session=session,
        user_id=current_user.id, # Who is doing the update (admin or user themselves)
        activity_type=ActivityType.UPDATE,
        resource_type=ResourceType.USER,
        resource_id=updated_user.id, # Who is being updated
        details={"updated_fields": list(update_dict.keys())},
        request=request,
    )
    
    return updated_user
