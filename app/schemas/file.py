import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FileCategory(StrEnum):
    """Logical bucket an uploaded file belongs to.

    Doubles as the Cloudinary sub-folder name, so files are organised on disk
    by purpose (e.g. ``uploads/user_profile_photo/<user_id>/...``). Stored as a
    plain string in the DB and validated here, mirroring ``User.role``.
    """

    GENERAL = "general"
    USER_PROFILE_PHOTO = "user_profile_photo"
    SUPPORT_ATTACHMENT = "support_attachment"


class FilePublic(BaseModel):
    """File metadata returned to clients.

    Excludes internal fields (``public_id``, ``uploaded_by_id``) that are only
    used server-side for Cloudinary management and ownership checks.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    content_type: str
    size: int
    filename: str | None = None
    category: FileCategory = FileCategory.GENERAL
    created_at: datetime
