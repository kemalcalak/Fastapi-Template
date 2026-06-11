import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
)

from app.core.messages.error_message import ErrorMessages
from app.schemas.admin_permission import Permission
from app.schemas.file import FilePublic

# Character classes a new password must contain, mirroring the frontend rule:
# at least one uppercase, one lowercase, one digit, and one special character.
_PASSWORD_CLASSES = (
    re.compile(r"[A-Z]"),
    re.compile(r"[a-z]"),
    re.compile(r"[0-9]"),
    re.compile(r'[!@#$%^&*(),.?":{}|<>]'),
)


def _validate_password_strength(value: str) -> str:
    """Reject new passwords that miss any required character class."""
    if not all(pattern.search(value) for pattern in _PASSWORD_CLASSES):
        raise ValueError(ErrorMessages.WEAK_PASSWORD)
    return value


# Applied to *new* passwords only (not current-password confirmations). Length is
# enforced by ``Field``; the validator adds the complexity requirement.
StrongPassword = Annotated[
    str,
    Field(min_length=8, max_length=40),
    AfterValidator(_validate_password_strength),
]


class SystemRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    USER = "user"


class Language(StrEnum):
    EN = "en"
    TR = "tr"


# Shared properties
class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: EmailStr = Field(max_length=255)
    is_active: bool = True
    is_verified: bool = False
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=100)
    role: str = Field(default="user", max_length=20)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: StrongPassword
    role: SystemRole = SystemRole.USER
    lang: Language = Language.EN

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in [role.value for role in SystemRole]:
            raise ValueError(ErrorMessages.INVALID_ROLE)
        return v


class UserRegister(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: StrongPassword
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=100)
    lang: Language = Language.EN


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: StrongPassword | None = None
    role: SystemRole | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in [role.value for role in SystemRole]:
            raise ValueError(ErrorMessages.INVALID_ROLE)
        return v


class UserUpdateMe(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=100)
    avatar_file_id: uuid.UUID | None = Field(default=None)


class UpdatePassword(BaseModel):
    current_password: str = Field(min_length=8, max_length=40)
    new_password: StrongPassword


class DeleteAccount(BaseModel):
    password: str = Field(min_length=8, max_length=40)
    lang: Language = Language.EN


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    role: SystemRole
    is_root_superadmin: bool = False
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None
    deletion_scheduled_at: datetime | None = None
    suspended_at: datetime | None = None
    avatar_file: FilePublic | None = None


class UserMe(UserPublic):
    """``/users/me`` payload: ``UserPublic`` plus RBAC permissions for admins.

    ``permissions`` is filled only for admins (superadmins get every key). For
    normal users it stays ``None`` and the serializer drops it entirely, so the
    field never reaches the client rather than surfacing as ``null``.
    """

    permissions: list[Permission] | None = None

    @model_serializer(mode="wrap")
    def _drop_null_permissions(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        """Omit the ``permissions`` key entirely when it is None (non-admins)."""
        data = handler(self)
        if self.permissions is None:
            data.pop("permissions", None)
        return data


class UserUpdateResponse(BaseModel):
    user: UserPublic
    message: str


class UsersPublic(BaseModel):
    data: list[UserPublic]
    count: int


class NewPassword(BaseModel):
    token: str
    new_password: StrongPassword
    lang: Language = Language.EN


class ForgotPassword(BaseModel):
    email: EmailStr = Field(max_length=255)
    lang: Language = Language.EN


class VerifyEmail(BaseModel):
    token: str
    lang: Language = Language.EN
