"""add deactivation fields to user

Revision ID: db36f1e8fa6b
Revises: 004c4063ef9a
Create Date: 2026-04-12 07:55:58.928635

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "db36f1e8fa6b"
down_revision: str | Sequence[str] | None = "004c4063ef9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "user",
        sa.Column("deletion_scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_user_deletion_due",
        "user",
        ["deletion_scheduled_at"],
        unique=False,
        postgresql_where=sa.text(
            "is_deleted = false AND deletion_scheduled_at IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_user_deletion_due", table_name="user")
    op.drop_column("user", "deletion_scheduled_at")
    op.drop_column("user", "deactivated_at")
