"""remove git_commit column from scripts table

Revision ID: b629d2878149
Revises: f3d04be66245
Create Date: 2026-01-25 12:42:30.570248

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b629d2878149'
down_revision: Union[str, Sequence[str], None] = 'f3d04be66245'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop git_commit column from scripts table
    op.drop_column('scripts', 'git_commit')


def downgrade() -> None:
    """Downgrade schema."""
    # Re-add git_commit column to scripts table
    op.add_column('scripts', sa.Column('git_commit', sa.VARCHAR(length=40), nullable=True))
