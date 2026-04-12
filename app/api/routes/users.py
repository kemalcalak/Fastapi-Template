from fastapi import APIRouter, Request, Response

from app.api.decorators import audit_unexpected_failure
from app.api.deps import CurrentActiveUser, CurrentUser, SessionDep
from app.core.config import settings
from app.core.messages.success_message import SuccessMessages
from app.core.rate_limit import rate_limit_strict
from app.schemas.msg import Message
from app.schemas.user import (
    DeleteAccount,
    UserPublic,
    UserUpdateMe,
    UserUpdateResponse,
)
from app.schemas.user_activity import ActivityType, ResourceType
from app.services.user_service import (
    deactivate_own_account_service,
    reactivate_own_account_service,
    update_user_service,
)

router = APIRouter()


@router.get("/me", response_model=UserPublic)
async def read_user_me(current_user: CurrentUser) -> UserPublic:
    """Get current user."""
    return current_user


@router.patch("/me", response_model=UserUpdateResponse)
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/users/me",
)
async def update_user_me(
    request: Request,
    session: SessionDep,
    current_user: CurrentActiveUser,
    user_in: UserUpdateMe,
) -> UserUpdateResponse:
    """Update own user details."""
    updated_user = await update_user_service(
        request=request,
        session=session,
        current_user=current_user,
        user_id=current_user.id,
        user_update=user_in,
    )
    return UserUpdateResponse(user=updated_user, message=SuccessMessages.USER_UPDATED)


@router.delete("/me", response_model=Message)
@rate_limit_strict("3/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/users/me (deactivate)",
)
async def delete_user_me(
    request: Request,
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
    body: DeleteAccount,
) -> Message:
    """Deactivate own account and schedule hard deletion after grace days.

    The account is not removed immediately — ``ACCOUNT_DELETION_GRACE_DAYS``
    later, the arq worker performs the irreversible delete. The user may
    cancel the deletion via ``POST /users/me/reactivate`` before that.
    The caller's auth cookies are cleared and their tokens revoked.
    """
    result = await deactivate_own_account_service(
        request=request,
        session=session,
        current_user=current_user,
        password=body.password,
    )
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(
        key="refresh_token", path=f"{settings.API_V1_STR}/auth/refresh"
    )
    return result


@router.post("/me/reactivate", response_model=Message)
@rate_limit_strict("5/minute")
@audit_unexpected_failure(
    activity_type=ActivityType.UPDATE,
    resource_type=ResourceType.USER,
    endpoint="/users/me/reactivate",
)
async def reactivate_user_me(
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    """Cancel a pending account deletion while still inside the grace window."""
    return await reactivate_own_account_service(
        request=request, session=session, current_user=current_user
    )
