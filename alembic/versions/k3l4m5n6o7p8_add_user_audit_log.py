"""add user_audit_log table for user-management audit trail

Revision ID: k3l4m5n6o7p8
Revises: a6048d483e4f
Create Date: 2026-09-20 06:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "k3l4m5n6o7p8"
down_revision = "a6048d483e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_username", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=255), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        op.f("ix_user_audit_log_target_username"), "user_audit_log", ["target_username"]
    )
    op.create_index(op.f("ix_user_audit_log_changed_at"), "user_audit_log", ["changed_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_audit_log_changed_at"), table_name="user_audit_log")
    op.drop_index(op.f("ix_user_audit_log_target_username"), table_name="user_audit_log")
    op.drop_table("user_audit_log")
