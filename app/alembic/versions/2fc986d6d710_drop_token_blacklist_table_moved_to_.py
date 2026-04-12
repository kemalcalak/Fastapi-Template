"""drop token_blacklist table (moved to redis)

Revision ID: 2fc986d6d710
Revises: db36f1e8fa6b
Create Date: 2026-04-12 07:57:41.442318

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2fc986d6d710"
down_revision: str | Sequence[str] | None = "db36f1e8fa6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: blacklist now lives in Redis."""
    op.drop_index(op.f("ix_token_blacklist_token"), table_name="token_blacklist")
    op.drop_table("token_blacklist")


def downgrade() -> None:
    """Downgrade schema: recreate the blacklist table."""
    op.create_table(
        "token_blacklist",
        sa.Column("id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("token", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("token_blacklist_pkey")),
    )
    op.create_index(
        op.f("ix_token_blacklist_token"), "token_blacklist", ["token"], unique=True
    )
