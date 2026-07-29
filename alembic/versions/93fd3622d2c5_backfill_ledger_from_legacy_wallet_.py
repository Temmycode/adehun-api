"""backfill ledger from legacy wallet balances

Revision ID: 93fd3622d2c5
Revises: 9fc5c9ab7a06
Create Date: 2026-07-29 13:28:16.048734

Wallets funded before the ledger existed have a balance with nothing behind it,
and that balance sits in the wrong bucket.

The old code credited `escrow_balance` on every successful charge, and nothing
ever released it — `transfer_to_other_account` was dead code and no agreement
held the money. So under the two-bucket model that balance is spendable money
mislabelled as escrow: left alone, the owner could never withdraw or spend it,
and every wallet would permanently violate the ledger invariant.

This migration, for each wallet with no ledger rows:

  1. Writes one `deposit` entry per successful ESCROW_DEPOSIT, keyed
     `dep_{paystack_reference}` — the exact reference the current webhook uses.
     That is deliberate: if Paystack ever redelivers one of those old
     `charge.success` events, the unique reference makes it a replay rather
     than a second credit.
  2. Adds a single `adjustment_credit` for any residual the deposits do not
     explain, so the invariant holds exactly rather than approximately.
  3. Moves the whole balance into `available_balance`.

Afterwards this must return zero rows, for every wallet, forever:

    SELECT w.id FROM wallet w LEFT JOIN transaction t ON t.wallet_id = w.id
    GROUP BY w.id
    HAVING w.available_balance <> COALESCE(SUM(t.available_delta), 0)
        OR w.escrow_balance    <> COALESCE(SUM(t.escrow_delta), 0);
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93fd3622d2c5'
down_revision: Union[str, Sequence[str], None] = '9fc5c9ab7a06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INSERT_ENTRY = sa.text(
    """
    INSERT INTO transaction (
        id, user_id, wallet_id, reference, amount, currency,
        available_delta, escrow_delta, balance_after, escrow_after,
        type, direction, status, description, metadata,
        paystack_transaction_id, created_at, processed_at
    ) VALUES (
        :id, :user_id, :wallet_id, :reference, :amount, 'NGN',
        :available_delta, 0, :balance_after, 0,
        :type, 'credit', 'completed', :description, :metadata,
        :paystack_transaction_id, :created_at, :created_at
    )
    """
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    legacy_wallets = bind.execute(
        sa.text(
            """
            SELECT w.id, w.user_id, w.available_balance, w.escrow_balance
            FROM wallet w
            WHERE NOT EXISTS (SELECT 1 FROM transaction t WHERE t.wallet_id = w.id)
              AND (w.available_balance > 0 OR w.escrow_balance > 0)
            """
        )
    ).all()

    for wallet_id, user_id, available, escrow in legacy_wallets:
        total = Decimal(available) + Decimal(escrow)
        running = Decimal("0.00")

        deposits = bind.execute(
            sa.text(
                """
                SELECT id, reference, amount, created_at
                FROM paystack_transaction
                WHERE user_id = :user_id
                  AND status = 'SUCCESS'
                  AND transaction_type = 'ESCROW_DEPOSIT'
                ORDER BY created_at
                """
            ),
            {"user_id": user_id},
        ).all()

        for ptxn_id, reference, amount, created_at in deposits:
            amount = Decimal(amount)
            if running + amount > total:
                # Do not manufacture more money than the wallet actually holds.
                break
            running += amount
            bind.execute(
                _INSERT_ENTRY,
                {
                    "id": str(uuid4()),
                    "user_id": user_id,
                    "wallet_id": wallet_id,
                    "reference": f"dep_{reference}",
                    "amount": amount,
                    "available_delta": amount,
                    "balance_after": running,
                    "type": "deposit",
                    "description": "Funded wallet",
                    "metadata": json.dumps({"backfilled": True}),
                    "paystack_transaction_id": ptxn_id,
                    "created_at": created_at,
                },
            )

        residual = total - running
        if residual > 0:
            bind.execute(
                _INSERT_ENTRY,
                {
                    "id": str(uuid4()),
                    "user_id": user_id,
                    "wallet_id": wallet_id,
                    "reference": f"opening_{wallet_id}",
                    "amount": residual,
                    "available_delta": residual,
                    "balance_after": total,
                    "type": "adjustment_credit",
                    "description": "Opening balance",
                    "metadata": json.dumps(
                        {
                            "backfilled": True,
                            "reason": "balance not explained by recorded deposits",
                            "legacy_available": str(available),
                            "legacy_escrow": str(escrow),
                        }
                    ),
                    "paystack_transaction_id": None,
                    "created_at": datetime.now(timezone.utc),
                },
            )

        # The old code credited escrow_balance on funding; nothing held it there.
        bind.execute(
            sa.text(
                """
                UPDATE wallet
                SET available_balance = :total, escrow_balance = 0, updated_at = :now
                WHERE id = :id
                """
            ),
            {"total": total, "now": datetime.now(timezone.utc), "id": wallet_id},
        )

    # Fail the migration rather than leave a wallet that cannot reconcile.
    drift = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT w.id
                FROM wallet w LEFT JOIN transaction t ON t.wallet_id = w.id
                GROUP BY w.id
                HAVING w.available_balance <> COALESCE(SUM(t.available_delta), 0)
                    OR w.escrow_balance    <> COALESCE(SUM(t.escrow_delta), 0)
            ) d
            """
        )
    ).scalar_one()
    if drift:
        raise RuntimeError(
            f"{drift} wallet(s) still do not reconcile with the ledger after backfill"
        )


def downgrade() -> None:
    """Downgrade schema.

    Removes only the rows this migration created and puts the balance back into
    escrow_balance, matching the pre-ledger behaviour.
    """
    bind = op.get_bind()

    wallets = bind.execute(
        sa.text(
            """
            SELECT DISTINCT wallet_id FROM transaction
            WHERE metadata @> '{"backfilled": true}'
            """
        )
    ).scalars().all()

    bind.execute(
        sa.text("DELETE FROM transaction WHERE metadata @> '{\"backfilled\": true}'")
    )

    for wallet_id in wallets:
        bind.execute(
            sa.text(
                """
                UPDATE wallet
                SET escrow_balance = escrow_balance + available_balance,
                    available_balance = 0
                WHERE id = :id
                """
            ),
            {"id": wallet_id},
        )
