"""add unique agreement participant constraint

Revision ID: 8692a810a7b1
Revises: 93fd3622d2c5
Create Date: 2026-08-14 09:59:03.812654

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8692a810a7b1'
down_revision: Union[str, Sequence[str], None] = '93fd3622d2c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
