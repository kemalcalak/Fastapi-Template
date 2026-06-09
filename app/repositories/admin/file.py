import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from app.models.file import File
from app.models.user import User
from app.utils.db_search import LIKE_ESCAPE_CHAR, ilike_contains


def _filtered_files_stmt(
    *,
    content_type: str | None,
    uploader: str | None,
) -> Select:
    """Build the filtered base statement shared by count and list queries."""
    stmt = select(File)
    if content_type:
        stmt = stmt.where(File.content_type == content_type)
    if uploader:
        # Inner-join the uploader and match on name or email. Files without an
        # uploader (uploaded_by_id IS NULL) are naturally excluded, which is
        # correct: they cannot match a person's name.
        pattern = ilike_contains(uploader)
        stmt = stmt.join(User, File.uploaded_by_id == User.id).where(
            or_(
                User.first_name.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                User.last_name.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                User.email.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
            )
        )
    return stmt


async def list_files_admin(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    content_type: str | None = None,
    uploader: str | None = None,
) -> tuple[Sequence[File], int]:
    """Return a filtered, paginated file page plus the matching total count."""
    base_stmt = _filtered_files_stmt(content_type=content_type, uploader=uploader)

    count_stmt = base_stmt.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = (await session.execute(count_stmt)).scalar_one()

    rows_stmt = (
        base_stmt.order_by(File.created_at.desc())
        .offset(skip)
        .limit(limit)
        .options(selectinload(File.uploaded_by))
    )
    files = (await session.execute(rows_stmt)).scalars().all()

    return files, total


async def get_file_admin(session: AsyncSession, file_id: uuid.UUID) -> File | None:
    """Fetch a single file with its uploader eager-loaded for the admin view."""
    stmt = (
        select(File).where(File.id == file_id).options(selectinload(File.uploaded_by))
    )
    return (await session.execute(stmt)).scalar_one_or_none()
