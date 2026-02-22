from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import SessionDep
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserPublic
from app.services.auth_service import login_service, register_service

router = APIRouter()


@router.post("/login", response_model=Token)
async def login_access_token(
    request: Request,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    return await login_service(
        request=request, session=session, email=form_data.username, password=form_data.password
    )


@router.post("/register", response_model=UserPublic)
async def register_user(
    request: Request, session: SessionDep, user_in: UserCreate
) -> UserPublic:
    """
    Register a new user.
    """
    return await register_service(
        request=request, session=session, user_create=user_in
    )
