"""extend paystack transaction for transfers

Revision ID: 0c6fbd8f4bd0
Revises: 52d0ec05beec
Create Date: 2026-07-29 12:31:41.353923

Adds the money-out columns. The paystack_transaction table previously only ever
recorded inbound charges.

Note: the corresponding model fixes (paystack_id -> BigInteger, status and
transaction_type -> String(50)) are MODEL-ONLY. The DB already had those types;
the model had drifted and was declaring a native PG enum and a plain Integer.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c6fbd8f4bd0'
down_revision: Union[str, Sequence[str], None] = '52d0ec05beec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "paystack_transaction",
        sa.Column("transfer_code", sa.String(100), nullable=True),
    )
    op.add_column(
        "paystack_transaction",
        sa.Column("recipient_code", sa.String(100), nullable=True),
    )
    op.add_column(
        "paystack_transaction", sa.Column("bank_account_id", sa.String(), nullable=True)
    )
    op.add_column(
        "paystack_transaction",
        sa.Column("failure_reason", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_paystack_transaction_transfer_code",
        "paystack_transaction",
        ["transfer_code"],
    )
    op.create_foreign_key(
        "fk_paystack_transaction_bank_account",
        "paystack_transaction",
        "bank_account",
        ["bank_account_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_paystack_transaction_bank_account",
        "paystack_transaction",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_paystack_transaction_transfer_code", table_name="paystack_transaction"
    )
    op.drop_column("paystack_transaction", "failure_reason")
    op.drop_column("paystack_transaction", "bank_account_id")
    op.drop_column("paystack_transaction", "recipient_code")
    op.drop_column("paystack_transaction", "transfer_code")
