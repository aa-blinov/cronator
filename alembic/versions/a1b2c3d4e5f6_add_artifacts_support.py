"""add artifacts support

Revision ID: a1b2c3d4e5f6
Revises: b629d2878149
Create Date: 2026-01-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "b629d2878149"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create artifacts table
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for artifacts table
    op.create_index("idx_artifact_execution", "artifacts", ["execution_id"])
    op.create_index("idx_artifact_created", "artifacts", ["created_at"])

    # Add artifacts tracking columns to executions table
    op.add_column(
        "executions", sa.Column("artifacts_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "executions",
        sa.Column("artifacts_size_bytes", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove artifacts tracking columns from executions table
    op.drop_column("executions", "artifacts_size_bytes")
    op.drop_column("executions", "artifacts_count")

    # Drop indexes for artifacts table
    op.drop_index("idx_artifact_created", table_name="artifacts")
    op.drop_index("idx_artifact_execution", table_name="artifacts")

    # Drop artifacts table
    op.drop_table("artifacts")
