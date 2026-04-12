"""drop is_deleted column from user

Revision ID: 01155384a530
Revises: a48b0bc6e988
Create Date: 2026-04-12 15:49:47.623781

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "01155384a530"
down_revision: str | Sequence[str] | None = "a48b0bc6e988"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop is_deleted column; rewrite the deletion-due index without it."""
    # Partial index references is_deleted in its WHERE clause, so it must be
    # dropped before the column can go, then recreated with a simpler predicate.
    op.drop_index(
        op.f("ix_user_deletion_due"),
        table_name="user",
        postgresql_where="((is_deleted = false) AND (deletion_scheduled_at IS NOT NULL))",
    )
    op.drop_index(op.f("ix_user_is_deleted"), table_name="user")
    op.drop_column("user", "is_deleted")
    op.create_index(
        "ix_user_deletion_due",
        "user",
        ["deletion_scheduled_at"],
        unique=False,
        postgresql_where=sa.text(
            "is_active = false AND deletion_scheduled_at IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Recreate is_deleted column and the original partial index."""
    op.drop_index(op.f("ix_user_deletion_due"), table_name="user")
    op.add_column(
        "user",
        sa.Column(
            "is_deleted",
            sa.BOOLEAN(),
            autoincrement=False,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("user", "is_deleted", server_default=None)
    op.create_index(op.f("ix_user_is_deleted"), "user", ["is_deleted"], unique=False)
    op.create_index(
        op.f("ix_user_deletion_due"),
        "user",
        ["deletion_scheduled_at"],
        unique=False,
        postgresql_where="((is_deleted = false) AND (deletion_scheduled_at IS NOT NULL))",
    )
