"""create paystack_transaction table

Revision ID: 6c819b8d4f12
Revises: 0520b744fc63
Create Date: 2026-07-22 16:30:23.317222

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6c819b8d4f12"
down_revision: Union[str, Sequence[str], None] = "0520b744fc63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create the paystack_transaction table
    op.create_table(
        "paystack_transaction",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("paystack_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column("payment_channel", sa.String(), nullable=True),
        sa.Column("gateway_response", sa.String(), nullable=True),
        sa.Column("raw_webhook_data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Create required indexes for fast querying and idempotency
    op.create_index(
        op.f("ix_paystack_transaction_id"),
        "paystack_transaction",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paystack_transaction_user_id"),
        "paystack_transaction",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paystack_transaction_reference"),
        "paystack_transaction",
        ["reference"],
        unique=True,
    )
    op.create_index(
        op.f("ix_paystack_transaction_paystack_id"),
        "paystack_transaction",
        ["paystack_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes first, then the table
    op.drop_index(
        op.f("ix_paystack_transaction_paystack_id"),
        table_name="paystack_transaction",
    )
    op.drop_index(
        op.f("ix_paystack_transaction_reference"),
        table_name="paystack_transaction",
    )
    op.drop_index(
        op.f("ix_paystack_transaction_user_id"),
        table_name="paystack_transaction",
    )
    op.drop_index(
        op.f("ix_paystack_transaction_id"),
        table_name="paystack_transaction",
    )
    op.drop_table("paystack_transaction")
