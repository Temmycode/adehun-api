"""extend transaction into ledger

Revision ID: d39cdb8297bf
Revises: b807c382afe3
Create Date: 2026-07-29 12:31:39.387595

Turns `transaction` into the unified wallet ledger: every naira that moves gets
a row here, whether it came from a Paystack charge, an agreement escrow
movement, or a bank payout.

Assumes the table is empty. It has never been written to by any code path — the
model existed but was never instantiated — so there is nothing to backfill. The
guard at the top of upgrade() enforces that assumption rather than trusting it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd39cdb8297bf'
down_revision: Union[str, Sequence[str], None] = 'b807c382afe3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT count(*) FROM transaction")).scalar_one()
    if existing:
        raise RuntimeError(
            f"transaction table has {existing} rows; this migration assumes it is "
            "empty. Backfill user_id / reference / the delta and balance_after "
            "columns manually before proceeding."
        )

    # --- Relax the legacy NOT NULLs -----------------------------------------
    # A wallet funding has no agreement and no participant.
    op.alter_column(
        "transaction", "agreement_id", nullable=True, existing_type=sa.String()
    )
    op.alter_column(
        "transaction", "participant_id", nullable=True, existing_type=sa.String()
    )

    # --- Ownership + idempotency --------------------------------------------
    op.add_column("transaction", sa.Column("user_id", sa.String(), nullable=False))
    op.add_column(
        "transaction", sa.Column("reference", sa.String(120), nullable=False)
    )
    op.add_column("transaction", sa.Column("group_id", sa.String(120), nullable=True))
    op.add_column(
        "transaction", sa.Column("counterparty_user_id", sa.String(), nullable=True)
    )

    # --- Money ---------------------------------------------------------------
    op.add_column(
        "transaction",
        sa.Column("currency", sa.String(3), server_default="NGN", nullable=False),
    )
    op.add_column(
        "transaction", sa.Column("available_delta", sa.Numeric(12, 2), nullable=False)
    )
    op.add_column(
        "transaction", sa.Column("escrow_delta", sa.Numeric(12, 2), nullable=False)
    )
    op.add_column(
        "transaction", sa.Column("balance_after", sa.Numeric(12, 2), nullable=False)
    )
    op.add_column(
        "transaction", sa.Column("escrow_after", sa.Numeric(12, 2), nullable=False)
    )

    # --- Classification + audit ----------------------------------------------
    op.add_column("transaction", sa.Column("direction", sa.String(10), nullable=False))
    op.add_column(
        "transaction", sa.Column("description", sa.String(255), nullable=True)
    )
    op.add_column(
        "transaction", sa.Column("metadata", postgresql.JSONB(), nullable=True)
    )

    # --- Tighten the existing columns ----------------------------------------
    op.alter_column(
        "transaction", "amount", type_=sa.Numeric(12, 2), existing_nullable=False
    )
    op.alter_column(
        "transaction", "type", type_=sa.String(32), existing_nullable=False
    )
    op.alter_column(
        "transaction", "status", type_=sa.String(20), existing_nullable=False
    )
    op.alter_column(
        "transaction",
        "created_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "transaction",
        "processed_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="processed_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "transaction", "wallet_id", nullable=False, existing_type=sa.String()
    )

    # --- Foreign keys ---------------------------------------------------------
    # f33dc310e54d created wallet_id with ON DELETE CASCADE, which would silently
    # delete ledger rows when a wallet is deleted. Rebuild it as RESTRICT.
    op.drop_constraint(
        "transaction_wallet_id_fkey", "transaction", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_transaction_wallet",
        "transaction",
        "wallet",
        ["wallet_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_transaction_user", "transaction", "user", ["user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_transaction_counterparty_user",
        "transaction",
        "user",
        ["counterparty_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_transaction_condition",
        "transaction",
        "condition",
        ["condition_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- Indexes --------------------------------------------------------------
    # ux_transaction_reference is THE durable idempotency guarantee: no retry,
    # from any layer, can insert the same movement twice.
    op.create_index(
        "ux_transaction_reference", "transaction", ["reference"], unique=True
    )
    op.create_index("ix_transaction_group_id", "transaction", ["group_id"])
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
    op.create_index("ix_transaction_agreement_id", "transaction", ["agreement_id"])
    op.create_index("ix_transaction_type", "transaction", ["type"])
    op.create_index("ix_transaction_status", "transaction", ["status"])
    op.create_index(
        "ix_transaction_paystack_transaction_id",
        "transaction",
        ["paystack_transaction_id"],
    )

    op.create_check_constraint(
        "ck_transaction_amount_positive", "transaction", "amount > 0"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_transaction_amount_positive", "transaction", type_="check")

    for index in (
        "ix_transaction_paystack_transaction_id",
        "ix_transaction_status",
        "ix_transaction_type",
        "ix_transaction_agreement_id",
        "ix_transaction_wallet_created",
        "ix_transaction_user_created",
        "ix_transaction_group_id",
        "ux_transaction_reference",
    ):
        op.drop_index(index, table_name="transaction")

    op.drop_constraint("fk_transaction_condition", "transaction", type_="foreignkey")
    op.drop_constraint(
        "fk_transaction_counterparty_user", "transaction", type_="foreignkey"
    )
    op.drop_constraint("fk_transaction_user", "transaction", type_="foreignkey")
    op.drop_constraint("fk_transaction_wallet", "transaction", type_="foreignkey")
    op.create_foreign_key(
        "transaction_wallet_id_fkey",
        "transaction",
        "wallet",
        ["wallet_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.alter_column(
        "transaction", "wallet_id", nullable=True, existing_type=sa.String()
    )
    op.alter_column(
        "transaction",
        "processed_at",
        type_=sa.DateTime(),
        existing_nullable=True,
    )
    op.alter_column(
        "transaction",
        "created_at",
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    op.alter_column(
        "transaction", "status", type_=sa.String(), existing_nullable=False
    )
    op.alter_column("transaction", "type", type_=sa.String(), existing_nullable=False)
    op.alter_column(
        "transaction", "amount", type_=sa.Numeric(), existing_nullable=False
    )

    for column in (
        "metadata",
        "description",
        "direction",
        "escrow_after",
        "balance_after",
        "escrow_delta",
        "available_delta",
        "currency",
        "counterparty_user_id",
        "group_id",
        "reference",
        "user_id",
    ):
        op.drop_column("transaction", column)

    op.alter_column(
        "transaction", "participant_id", nullable=False, existing_type=sa.String()
    )
    op.alter_column(
        "transaction", "agreement_id", nullable=False, existing_type=sa.String()
    )
