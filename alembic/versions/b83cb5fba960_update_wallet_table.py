"""update wallet table

Revision ID: b83cb5fba960
Revises: f33dc310e54d
Create Date: 2026-07-29 11:28:10.245443

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b83cb5fba960"
down_revision: Union[str, Sequence[str], None] = "f33dc310e54d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "wallet",
        sa.Column(
            "available_balance",
            sa.DECIMAL(),
            server_default="0.00",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("wallet", "available_balance")
