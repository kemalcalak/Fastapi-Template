import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.file import FilePublic


class TicketStatus(StrEnum):
    """Lifecycle states of a support ticket.

    OPEN — newly created, awaiting first admin response.
    PENDING — admin replied, waiting on the user.
    ANSWERED — user replied, back in the admin queue.
    CLOSED — resolved; no further messages expected.
    """

    OPEN = "open"
    PENDING = "pending"
    ANSWERED = "answered"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    """Admin-assigned urgency of a ticket."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class SenderRole(StrEnum):
    """Which side of the conversation authored a message."""

    USER = "user"
    ADMIN = "admin"


# --- Message-level schemas -------------------------------------------------


class SupportMessageAttachmentRead(BaseModel):
    """An uploaded file bound to a support message, as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file: FilePublic


class SupportMessageRead(BaseModel):
    """A single message within a ticket thread."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender_id: uuid.UUID | None = None
    sender_role: SenderRole
    body: str
    read_at: datetime | None = None
    created_at: datetime
    attachments: list[SupportMessageAttachmentRead] = Field(default_factory=list)


class MessageCreate(BaseModel):
    """Payload to post a reply into an existing ticket."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=10_000)
    attachment_file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


# --- Ticket-level schemas (user side) --------------------------------------


class TicketCreate(BaseModel):
    """Payload to open a new ticket with its first message."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)
    attachment_file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class SupportTicketListItem(BaseModel):
    """Row shape in the user's own ticket listing."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    status: TicketStatus
    priority: TicketPriority
    last_message_at: datetime
    created_at: datetime
    closed_at: datetime | None = None
    unread_count: int = 0


class SupportTicketListResponse(BaseModel):
    """Paginated listing of the caller's tickets."""

    data: list[SupportTicketListItem]
    total: int
    skip: int
    limit: int


class SupportTicketDetail(BaseModel):
    """A single ticket with its full message thread."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    status: TicketStatus
    priority: TicketPriority
    last_message_at: datetime
    created_at: datetime
    closed_at: datetime | None = None
    messages: list[SupportMessageRead] = Field(default_factory=list)


# --- Ticket-level schemas (admin side) -------------------------------------


class SupportTicketUser(BaseModel):
    """Minimal ticket-owner identity embedded in admin ticket views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None


class AdminTicketListItem(BaseModel):
    """Row shape in the admin ticket queue."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    status: TicketStatus
    priority: TicketPriority
    last_message_at: datetime
    created_at: datetime
    closed_at: datetime | None = None
    assigned_admin_id: uuid.UUID | None = None
    user: SupportTicketUser
    unread_count: int = 0


class AdminTicketListResponse(BaseModel):
    """Paginated admin ticket queue payload."""

    data: list[AdminTicketListItem]
    total: int
    skip: int
    limit: int


class AdminTicketDetail(SupportTicketDetail):
    """Admin view of a ticket: the full thread plus owner/assignment metadata."""

    assigned_admin_id: uuid.UUID | None = None
    user: SupportTicketUser


class AdminTicketUpdate(BaseModel):
    """Fields an admin may change on a ticket."""

    model_config = ConfigDict(extra="forbid")

    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assigned_admin_id: uuid.UUID | None = None


# --- Shared response wrappers ----------------------------------------------


class SupportTicketResponse(BaseModel):
    """Standard response after creating or mutating a ticket."""

    ticket: SupportTicketDetail
    message: str


class SupportMessageResponse(BaseModel):
    """Standard response after posting a message into a ticket."""

    data: SupportMessageRead
    message: str
