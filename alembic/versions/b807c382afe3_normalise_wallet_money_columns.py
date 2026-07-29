"""normalise wallet money columns

Revision ID: b807c382afe3
Revises: b83cb5fba960
Create Date: 2026-07-29 12:31:38.913321

Brings the wallet table up to the two-bucket ledger model:
  - merges any duplicate wallets (one wallet per user is now enforced)
  - both balances become NUMERIC(12,2)
  - adds currency
  - CHECK constraints so a balance can never go negative, even if something
    ever bypasses WalletRepository._apply_ledger_entry

created_at/updated_at need no DDL — they are already timestamptz.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b807c382afe3'
down_revision: Union[str, Sequence[str], None] = 'b83cb5fba960'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # --- 1. Collapse duplicate wallets --------------------------------------
    # get_user_wallet used .first() while two separate code paths created a
    # wallet on miss, so duplicates were possible. Sum the balances onto the
    # oldest row, then delete the rest. This is the only lossy step in the
    # whole migration chain.
    duplicates = bind.execute(
        sa.text(
            "SELECT count(*) FROM ("
            "  SELECT user_id FROM wallet GROUP BY user_id HAVING count(*) > 1"
            ") d"
        )
    ).scalar_one()

    if duplicates:
        op.execute(
            """
            WITH sums AS (
                SELECT user_id,
                       SUM(available_balance) AS a,
                       SUM(escrow_balance)    AS e
                FROM wallet GROUP BY user_id
            ), keep AS (
                SELECT DISTINCT ON (user_id) id, user_id FROM wallet
                ORDER BY user_id, created_at, id
            )
            UPDATE wallet w
            SET available_balance = s.a, escrow_balance = s.e
            FROM keep k JOIN sums s ON s.user_id = k.user_id
            WHERE w.id = k.id
            """
        )
        op.execute(
            """
            DELETE FROM wallet WHERE id NOT IN (
                SELECT DISTINCT ON (user_id) id FROM wallet
                ORDER BY user_id, created_at, id
            )
            """
        )

    # --- 2. Money precision -------------------------------------------------
    # available_balance was created as a bare DECIMAL by b83cb5fba960.
    op.alter_column(
        "wallet",
        "available_balance",
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        existing_server_default="0.00",
        postgresql_using="ROUND(available_balance, 2)",
    )
    op.alter_column(
        "wallet",
        "escrow_balance",
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        existing_server_default="0.00",
    )

    # --- 3. Currency --------------------------------------------------------
    op.add_column(
        "wallet",
        sa.Column("currency", sa.String(3), server_default="NGN", nullable=False),
    )

    # --- 4. One wallet per user --------------------------------------------
    op.drop_index("ix_wallet_user_id", table_name="wallet")
    op.create_unique_constraint("uq_wallet_user_id", "wallet", ["user_id"])

    # --- 5. Balances can never go negative ----------------------------------
    op.create_check_constraint(
        "ck_wallet_available_non_negative", "wallet", "available_balance >= 0"
    )
    op.create_check_constraint(
        "ck_wallet_escrow_non_negative", "wallet", "escrow_balance >= 0"
    )


def downgrade() -> None:
    """Downgrade schema.

    The duplicate-wallet merge is not reversible; everything else is.
    """
    op.drop_constraint("ck_wallet_escrow_non_negative", "wallet", type_="check")
    op.drop_constraint("ck_wallet_available_non_negative", "wallet", type_="check")
    op.drop_constraint("uq_wallet_user_id", "wallet", type_="unique")
    op.create_index("ix_wallet_user_id", "wallet", ["user_id"])
    op.drop_column("wallet", "currency")
    op.alter_column(
        "wallet",
        "available_balance",
        type_=sa.DECIMAL(),
        existing_nullable=False,
        existing_server_default="0.00",
    )
