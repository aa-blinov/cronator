"""add last_failure_alert_at to scripts

Revision ID: a6048d483e4f
Revises: j2k3l4m5n6o7
Create Date: 2026-09-19 17:17:11.030673

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a6048d483e4f"
down_revision = "j2k3l4m5n6o7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column("last_failure_alert_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scripts", "last_failure_alert_at")
