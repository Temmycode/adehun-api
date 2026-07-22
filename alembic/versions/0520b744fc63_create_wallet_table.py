"""create wallet table

Revision ID: 0520b744fc63
Revises: 58581e01bdc5
Create Date: 2026-07-22 16:21:25.168766

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0520b744fc63"
down_revision: Union[str, Sequence[str], None] = "58581e01bdc5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "wallet",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        # Fixed: Match 'escrow_balance' from your webhook code, and add financial precision
        sa.Column(
            "escrow_balance",
            sa.Numeric(precision=12, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Ensure table name matches your actual users table (e.g., 'users' vs 'user')
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Critical for fast lookups during webhook processing
    op.create_index(op.f("ix_wallet_id"), "wallet", ["id"], unique=False)
    op.create_index(op.f("ix_wallet_user_id"), "wallet", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_wallet_user_id"), table_name="wallet")
    op.drop_index(op.f("ix_wallet_id"), table_name="wallet")
    op.drop_table("wallet")
