"""add name column to asset_file table

Revision ID: ddf1c9d2a5ca
Revises: 35987cfa13e1
Create Date: 2026-07-20 09:15:32.684624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ddf1c9d2a5ca'
down_revision: Union[str, Sequence[str], None] = '35987cfa13e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('asset_file', sa.Column('name', sa.String(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('asset_file', 'name')
