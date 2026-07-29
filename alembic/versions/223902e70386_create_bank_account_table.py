"""create bank account table

Revision ID: 223902e70386
Revises: d39cdb8297bf
Create Date: 2026-07-29 12:31:39.916767

Payout destinations, each backed by a Paystack transfer recipient.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '223902e70386'
down_revision: Union[str, Sequence[str], None] = 'd39cdb8297bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "bank_account",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("account_number", sa.String(20), nullable=False),
        sa.Column("bank_code", sa.String(10), nullable=False),
        sa.Column("bank_name", sa.String(120), nullable=False),
        sa.Column("account_name", sa.String(120), nullable=False),
        sa.Column("recipient_code", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), server_default="NGN", nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_account_user_id", "bank_account", ["user_id"])
    op.create_index(
        "ix_bank_account_recipient_code",
        "bank_account",
        ["recipient_code"],
        unique=True,
    )

    # Partial unique indexes — not cleanly expressible via __table_args__.
    # A user cannot save the same account twice while it is active...
    op.execute(
        """
        CREATE UNIQUE INDEX ux_bank_account_user_bank_acct
        ON bank_account (user_id, bank_code, account_number)
        WHERE is_active
        """
    )
    # ...and can have at most one default account.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_bank_account_one_default
        ON bank_account (user_id)
        WHERE is_default AND is_active
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ux_bank_account_one_default")
    op.execute("DROP INDEX IF EXISTS ux_bank_account_user_bank_acct")
    op.drop_index("ix_bank_account_recipient_code", table_name="bank_account")
    op.drop_index("ix_bank_account_user_id", table_name="bank_account")
    op.drop_table("bank_account")
