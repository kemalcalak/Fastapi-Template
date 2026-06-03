import asyncio
import io
import logging
from dataclasses import dataclass
from typing import cast

import cloudinary  # pyright: ignore[reportMissingTypeStubs]
import cloudinary.uploader  # pyright: ignore[reportMissingTypeStubs]

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadResult:
    """Normalized Cloudinary upload result — only the fields we persist."""

    url: str
    public_id: str


def is_configured() -> bool:
    """Return True when all Cloudinary credentials are present in settings."""
    return bool(
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    )


def _configure() -> None:
    """Apply Cloudinary credentials to the SDK, failing fast when unset.

    Raises RuntimeError when any credential is missing so callers surface an
    explicit configuration error instead of an opaque SDK failure.
    """
    if not is_configured():
        raise RuntimeError("Cloudinary credentials are not configured.")
    cloudinary.config(  # pyright: ignore[reportUnknownMemberType]
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


async def upload_file(
    content: bytes,
    *,
    folder: str | None = None,
    resource_type: str = "image",
) -> UploadResult:
    """Upload raw bytes to Cloudinary and return the persisted fields.

    The blocking SDK call runs in a worker thread. Raises RuntimeError when
    credentials are missing and propagates SDK errors to the caller.
    """
    _configure()
    target_folder = folder or settings.CLOUDINARY_UPLOAD_FOLDER

    def _upload_sync() -> dict[str, object]:
        """Run the blocking Cloudinary upload inside asyncio.to_thread."""
        raw = cloudinary.uploader.upload(  # pyright: ignore[reportUnknownMemberType, reportAny]
            io.BytesIO(content),
            folder=target_folder,
            resource_type=resource_type,
        )
        return cast("dict[str, object]", raw)

    result = await asyncio.to_thread(_upload_sync)
    return UploadResult(
        url=str(result["secure_url"]),
        public_id=str(result["public_id"]),
    )


async def delete_file(public_id: str, *, resource_type: str = "image") -> bool:
    """Delete a Cloudinary asset by public_id, returning True on success.

    Failures are logged and swallowed (returns False) so best-effort cleanup
    never blocks the primary request flow.
    """
    if not is_configured():
        logger.warning(f"Cloudinary not configured; skipping delete of {public_id}")
        return False
    _configure()

    def _destroy_sync() -> dict[str, object]:
        """Run the blocking Cloudinary destroy inside asyncio.to_thread."""
        raw = cloudinary.uploader.destroy(  # pyright: ignore[reportUnknownMemberType, reportAny]
            public_id,
            resource_type=resource_type,
        )
        return cast("dict[str, object]", raw)

    try:
        result = await asyncio.to_thread(_destroy_sync)
        return result.get("result") == "ok"
    except Exception as e:
        logger.error(f"Failed to delete Cloudinary asset {public_id}: {e}")
        return False
