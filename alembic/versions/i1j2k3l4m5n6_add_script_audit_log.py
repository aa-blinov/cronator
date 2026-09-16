"""add script audit log table

Revision ID: i1j2k3l4m5n6
Revises: c7e2f1a9b3d8
Create Date: 2026-09-16 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "i1j2k3l4m5n6"
down_revision = "c7e2f1a9b3d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "script_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("script_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=255), nullable=False, server_default="system"),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        op.f("ix_script_audit_log_script_id"),
        "script_audit_log",
        ["script_id"],
    )
    op.create_index(
        op.f("ix_script_audit_log_changed_at"),
        "script_audit_log",
        ["changed_at"],
    )
    op.create_foreign_key(
        "fk_script_audit_log_script_id",
        "script_audit_log",
        "scripts",
        ["script_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_script_audit_log_changed_at"), table_name="script_audit_log")
    op.drop_index(op.f("ix_script_audit_log_script_id"), table_name="script_audit_log")
    op.drop_table("script_audit_log")
