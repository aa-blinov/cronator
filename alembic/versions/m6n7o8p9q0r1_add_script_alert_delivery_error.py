"""add script alert delivery error columns

Revision ID: m6n7o8p9q0r1
Revises: l4m5n6o7p8q9
Create Date: 2026-11-20 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "m6n7o8p9q0r1"
down_revision = "l4m5n6o7p8q9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An alert that failed to leave (expired SMTP password, webhook
    # answering 500) was previously visible only in the application log.
    op.add_column("scripts", sa.Column("last_alert_error", sa.Text(), nullable=True))
    op.add_column(
        "scripts",
        sa.Column("last_alert_error_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scripts", "last_alert_error_at")
    op.drop_column("scripts", "last_alert_error")
