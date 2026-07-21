"""add size to asset_file table

Revision ID: 58581e01bdc5
Revises: ddf1c9d2a5ca
Create Date: 2026-07-20 09:42:11.451630

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "58581e01bdc5"
down_revision: Union[str, Sequence[str], None] = "ddf1c9d2a5ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("asset_file", sa.Column("size", sa.Float(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("asset_file", "size")
