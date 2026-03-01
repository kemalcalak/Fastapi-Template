from fastapi import APIRouter, HTTPException, Request

from app.api.deps import CurrentUser, SessionDep
from app.core.messages.error_message import ErrorMessages
from app.schemas.msg import Message
from app.schemas.user import DeleteAccount, UserPublic, UserUpdateMe
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType
from app.services.user_activity_service import log_activity
from app.services.user_service import delete_own_account_service, update_user_service

router = APIRouter()


@router.get("/me", response_model=UserPublic)
async def read_user_me(
    request: Request, session: SessionDep, current_user: CurrentUser
) -> UserPublic:
    """
    Get current user.
    """
    try:
        return current_user
    except Exception as e:
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.READ,
            resource_type=ResourceType.USER,
            resource_id=current_user.id,
            status=ActivityStatus.FAILURE,
            details={"error": str(e)},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
    user_in: UserUpdateMe,
) -> UserPublic:
    """
    Update own user details.
    """
    try:
        return await update_user_service(
            request=request,
            session=session,
            current_user=current_user,
            user_id=current_user.id,
            user_update=user_in,
        )
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.UPDATE,
            resource_type=ResourceType.USER,
            resource_id=current_user.id,
            status=ActivityStatus.FAILURE,
            details={"error": str(e)},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)


@router.delete("/me", response_model=Message)
async def delete_user_me(
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
    body: DeleteAccount,
) -> Message:
    """
    Delete own user profile with password confirmation.
    """
    try:
        return await delete_own_account_service(
            request=request,
            session=session,
            current_user=current_user,
            password=body.password,
        )
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            session=session,
            user_id=current_user.id,
            activity_type=ActivityType.DELETE,
            resource_type=ResourceType.USER,
            resource_id=current_user.id,
            status=ActivityStatus.FAILURE,
            details={"error": str(e)},
            request=request,
        )
        raise HTTPException(status_code=500, detail=ErrorMessages.INTERNAL_SERVER_ERROR)
