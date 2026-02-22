import uuid
from datetime import datetime
from enum import Enum

from pydantic import EmailStr, field_validator
from sqlmodel import Field, SQLModel

from app.core.messages.error_message import ErrorMessages
from app.models.user import UserBase


class SystemRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=40)
    role: SystemRole = SystemRole.USER

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in [role.value for role in SystemRole]:
            raise ValueError(ErrorMessages.INVALID_ROLE)
        return v


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=40)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=100)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=40)
    role: SystemRole | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in [role.value for role in SystemRole]:
            raise ValueError(ErrorMessages.INVALID_ROLE)
        return v


class UserUpdateMe(SQLModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=100)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=40)
    new_password: str = Field(min_length=8, max_length=40)


class DeleteAccount(SQLModel):
    password: str = Field(min_length=8, max_length=40)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    role: SystemRole
    created_at: datetime
    updated_at: datetime


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=40)
