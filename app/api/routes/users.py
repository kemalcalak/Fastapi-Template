from typing import Any

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.schemas.msg import Message
from app.schemas.user import DeleteAccount, UserPublic, UserUpdate, UserUpdateMe
from app.services.user_service import delete_own_account_service, update_user_service

router = APIRouter()


@router.get("/me", response_model=UserPublic)
async def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    session: SessionDep, current_user: CurrentUser, user_in: UserUpdateMe
) -> Any:
    """
    Update own user details.
    """
    user_update = UserUpdate(**user_in.model_dump(exclude_unset=True))
    return await update_user_service(
        session=session, user_id=current_user.id, user_update=user_update
    )


@router.delete("/me", response_model=Message)
async def delete_user_me(
    session: SessionDep, current_user: CurrentUser, body: DeleteAccount
) -> Any:
    """
    Delete own user profile with password confirmation.
    """
    return await delete_own_account_service(
        session=session, current_user=current_user, password=body.password
    )
