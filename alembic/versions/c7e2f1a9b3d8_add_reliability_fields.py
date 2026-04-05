"""add reliability fields

Revision ID: c7e2f1a9b3d8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e2f1a9b3d8"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add reliability columns to scripts table
    op.add_column(
        "scripts",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scripts",
        sa.Column("retry_delay", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column(
        "scripts",
        sa.Column("max_retry_window", sa.Integer(), nullable=False, server_default="3600"),
    )
    op.add_column(
        "scripts",
        sa.Column("prevent_overlap", sa.Boolean(), nullable=False, server_default="true"),
    )

    # Add stats columns to scripts table
    op.add_column(
        "scripts",
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scripts",
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scripts",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )

    # Add attempt column to executions table
    op.add_column(
        "executions",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove attempt column from executions table
    op.drop_column("executions", "attempt")

    # Remove stats columns from scripts table
    op.drop_column("scripts", "consecutive_failures")
    op.drop_column("scripts", "last_failure_at")
    op.drop_column("scripts", "last_success_at")

    # Remove reliability columns from scripts table
    op.drop_column("scripts", "prevent_overlap")
    op.drop_column("scripts", "max_retry_window")
    op.drop_column("scripts", "retry_delay")
    op.drop_column("scripts", "retry_count")
