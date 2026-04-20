import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import ActivityDetails
from app.schemas.user import SystemRole
from app.schemas.user_activity import ActivityStatus, ActivityType, ResourceType


class AdminUserUpdate(BaseModel):
    """Fields an admin may change on another user's account.

    Email is intentionally NOT in this schema: an admin must never be able to
    rewrite a user's identity (login + recovery channel). With ``extra=forbid``
    a stray ``email`` key in the request body returns 422 — defence in depth
    on top of the FE form which doesn't expose the field at all.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=100)
    role: SystemRole | None = None
    is_active: bool | None = None
    is_verified: bool | None = None


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
    suspended_at: datetime | None = None


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


class AdminStats(BaseModel):
    """Aggregate counts powering the admin dashboard overview."""

    users_total: int
    users_active: int
    users_verified: int
    users_admins: int
    activities_total: int
