"""Initial schema with all tables

Revision ID: 7a45991c91e2
Revises:
Create Date: 2026-01-25 10:54:05.081979

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a45991c91e2"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create scripts table
    op.create_table(
        "scripts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("python_version", sa.String(length=20), nullable=False),
        sa.Column("dependencies", sa.Text(), nullable=False),
        sa.Column("alert_on_failure", sa.Boolean(), nullable=False),
        sa.Column("alert_on_success", sa.Boolean(), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column("misfire_grace_time", sa.Integer(), nullable=False),
        sa.Column("working_directory", sa.String(length=500), nullable=False),
        sa.Column("environment_vars", sa.Text(), nullable=False),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("git_commit", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scripts_name", "scripts", ["name"], unique=True)

    # Create executions table
    op.create_table(
        "executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("script_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.String(length=50), nullable=False),
        sa.Column("is_test", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_script_started", "executions", ["script_id", "started_at"], unique=False)
    op.create_index("idx_status_started", "executions", ["status", "started_at"], unique=False)
    op.create_index("ix_executions_script_id", "executions", ["script_id"], unique=False)
    op.create_index("ix_executions_started_at", "executions", ["started_at"], unique=False)
    op.create_index("ix_executions_status", "executions", ["status"], unique=False)

    # Create script_versions table
    op.create_table(
        "script_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("script_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("dependencies", sa.Text(), nullable=False),
        sa.Column("python_version", sa.String(length=20), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column("environment_vars", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_script_versions_script_created",
        "script_versions",
        ["script_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_script_versions_script_version",
        "script_versions",
        ["script_id", "version_number"],
        unique=False,
    )
    op.create_index("ix_script_versions_script_id", "script_versions", ["script_id"], unique=False)

    # Create settings table
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("settings")
    op.drop_index("ix_script_versions_script_id", table_name="script_versions")
    op.drop_index("idx_script_versions_script_version", table_name="script_versions")
    op.drop_index("idx_script_versions_script_created", table_name="script_versions")
    op.drop_table("script_versions")
    op.drop_index("ix_executions_status", table_name="executions")
    op.drop_index("ix_executions_started_at", table_name="executions")
    op.drop_index("ix_executions_script_id", table_name="executions")
    op.drop_index("idx_status_started", table_name="executions")
    op.drop_index("idx_script_started", table_name="executions")
    op.drop_table("executions")
    op.drop_index("ix_scripts_name", table_name="scripts")
    op.drop_table("scripts")
