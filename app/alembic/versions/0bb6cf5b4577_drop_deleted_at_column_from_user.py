"""drop deleted_at column from user

Revision ID: 0bb6cf5b4577
Revises: 01155384a530
Create Date: 2026-04-12 16:10:20.195589

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0bb6cf5b4577"
down_revision: str | Sequence[str] | None = "01155384a530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop unused deleted_at column.

    The partial index ``ix_user_deletion_due`` is intentionally preserved —
    autogenerate wants to drop it because the predicate isn't reflected on
    the model, but the deletion worker depends on it for performance.
    """
    op.drop_column("user", "deleted_at")


def downgrade() -> None:
    """Recreate deleted_at column."""
    op.add_column(
        "user",
        sa.Column(
            "deleted_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
