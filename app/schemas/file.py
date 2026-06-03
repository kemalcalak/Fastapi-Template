import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    created_at: datetime
