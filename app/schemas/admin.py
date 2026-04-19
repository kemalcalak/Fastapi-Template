import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.messages.error_message import ErrorMessages
from app.schemas.common import ActivityDetails
from app.schemas.user import SystemRole
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType


class AdminUserUpdate(BaseModel):
    """Fields an admin may change on another user's account."""

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=255)
    role: SystemRole | None = None
    is_active: bool | None = None
    is_verified: bool | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: SystemRole | None) -> SystemRole | None:
        """Ensure role, if provided, matches the SystemRole enum."""
        if v is not None and v not in SystemRole:
            raise ValueError(ErrorMessages.INVALID_ROLE)
        return v


class AdminUserListItem(BaseModel):
    """Row shape returned by the admin user listing endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    role: SystemRole
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None
    deletion_scheduled_at: datetime | None = None


class AdminUserListResponse(BaseModel):
    """Paginated admin user listing payload."""

    data: list[AdminUserListItem]
    total: int
    skip: int
    limit: int


class AdminUserDetail(AdminUserListItem):
    """Full admin view of a single user. Currently identical to the list row."""


class AdminUserUpdateResponse(BaseModel):
    """Standard response returned after mutating a user via the admin API."""

    user: AdminUserDetail
    message: str


class AdminActivityItem(BaseModel):
    """Row shape returned by the admin activity log endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    activity_type: ActivityType
    resource_type: ResourceType
    resource_id: uuid.UUID | None = None
    details: ActivityDetails
    status: ActivityStatus
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime


class AdminActivityListResponse(BaseModel):
    """Paginated activity log payload."""

    data: list[AdminActivityItem]
    total: int
    skip: int
    limit: int
