"""update the transaction table

Revision ID: f33dc310e54d
Revises: 6c819b8d4f12
Create Date: 2026-07-29 10:44:21.718506

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f33dc310e54d"
down_revision: Union[str, Sequence[str], None] = "6c819b8d4f12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transaction",
        sa.Column(
            "wallet_id",
            sa.String(),
            sa.ForeignKey("wallet.id", ondelete="CASCADE"),
        ),
    )
    op.add_column(
        "transaction",
        sa.Column(
            "paystack_transaction_id",
            sa.String(),
            sa.ForeignKey("paystack_transaction.id"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('transaction', 'wallet_id')
    op.drop_column('transaction', 'paystack_transaction_id')
