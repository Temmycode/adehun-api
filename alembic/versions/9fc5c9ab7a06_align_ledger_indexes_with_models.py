"""align ledger indexes with models

Revision ID: 9fc5c9ab7a06
Revises: 0c6fbd8f4bd0
Create Date: 2026-07-29 12:43:29.111336

Housekeeping so `alembic revision --autogenerate` produces an empty diff:

  - The two composite ledger indexes were created with an explicit
    `created_at DESC`. Alembic cannot reliably compare expression indexes, and
    the DESC buys nothing — Postgres scans a plain btree backwards just as
    efficiently for `WHERE user_id = ? ORDER BY created_at DESC`. Recreate them
    as plain column indexes.
  - `ix_wallet_id` and `ix_paystack_transaction_id` are indexes on the primary
    key column, fully redundant with the PK's own unique index. They predate
    this work; drop them rather than teach the models about dead weight.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9fc5c9ab7a06'
down_revision: Union[str, Sequence[str], None] = '0c6fbd8f4bd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_transaction_user_created", table_name="transaction")
    op.drop_index("ix_transaction_wallet_created", table_name="transaction")
    op.create_index(
        "ix_transaction_user_created", "transaction", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_transaction_wallet_created", "transaction", ["wallet_id", "created_at"]
    )

    op.drop_index("ix_wallet_id", table_name="wallet")
    op.drop_index("ix_paystack_transaction_id", table_name="paystack_transaction")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index("ix_paystack_transaction_id", "paystack_transaction", ["id"])
    op.create_index("ix_wallet_id", "wallet", ["id"])

    op.drop_index("ix_transaction_wallet_created", table_name="transaction")
    op.drop_index("ix_transaction_user_created", table_name="transaction")
    op.create_index(
        "ix_transaction_user_created",
        "transaction",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_transaction_wallet_created",
        "transaction",
        ["wallet_id", sa.text("created_at DESC")],
    )
