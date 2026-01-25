"""update_default_python_version_to_3_12

Revision ID: f3d04be66245
Revises: 7a45991c91e2
Create Date: 2026-01-25 11:08:43.977532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3d04be66245'
down_revision: Union[str, Sequence[str], None] = '7a45991c91e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Update default python_version from 3.11 to 3.12 in scripts table
    op.alter_column(
        'scripts',
        'python_version',
        existing_type=sa.String(20),
        server_default='3.12',
        existing_nullable=True
    )
    
    # Update default python_version from 3.11 to 3.12 in script_versions table
    op.alter_column(
        'script_versions',
        'python_version',
        existing_type=sa.String(20),
        server_default='3.12',
        existing_nullable=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Revert default python_version from 3.12 back to 3.11 in scripts table
    op.alter_column(
        'scripts',
        'python_version',
        existing_type=sa.String(20),
        server_default='3.11',
        existing_nullable=True
    )
    
    # Revert default python_version from 3.12 back to 3.11 in script_versions table
    op.alter_column(
        'script_versions',
        'python_version',
        existing_type=sa.String(20),
        server_default='3.11',
        existing_nullable=False
    )
