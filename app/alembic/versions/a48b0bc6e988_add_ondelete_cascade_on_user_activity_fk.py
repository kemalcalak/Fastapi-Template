"""add ondelete cascade on user_activity fk

Revision ID: a48b0bc6e988
Revises: 2fc986d6d710
Create Date: 2026-04-12 08:07:38.336523

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a48b0bc6e988"
down_revision: str | Sequence[str] | None = "2fc986d6d710"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Swap the user_activity FK for one with ON DELETE CASCADE.

    Lets Postgres fan out the cascade on hard-delete in a single statement
    instead of the ORM issuing one DELETE per activity row.
    """
    op.drop_constraint(
        "user_activity_user_id_fkey", "user_activity", type_="foreignkey"
    )
    op.create_foreign_key(
        "user_activity_user_id_fkey",
        "user_activity",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Revert to a non-cascading FK."""
    op.drop_constraint(
        "user_activity_user_id_fkey", "user_activity", type_="foreignkey"
    )
    op.create_foreign_key(
        "user_activity_user_id_fkey",
        "user_activity",
        "user",
        ["user_id"],
        ["id"],
    )
