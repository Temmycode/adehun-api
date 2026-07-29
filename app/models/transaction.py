"""The wallet ledger.

INVARIANT — everything in the wallet feature depends on this:

    A `Transaction` row is written ONLY when a balance actually moves. Its
    `available_delta` / `escrow_delta` are the exact signed amounts applied.
    Therefore, for every wallet, unconditionally:

        wallet.available_balance == SUM(available_delta)
        wallet.escrow_balance    == SUM(escrow_delta)

    `status` is presentational and NEVER affects a balance. A reversal is a
    *new row*, never a mutation of an old one.

Rows are only ever written by `WalletRepository._apply_ledger_entry`.
`TransactionRepository` is read-only by design.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.common.enums import LedgerDirection, LedgerEntryStatus, LedgerEntryType

if TYPE_CHECKING:
    from .agreement import Agreement
    from .agreement_participant import AgreementParticipant


class Transaction(SQLModel, table=True):
    # Indexes and constraints are declared explicitly rather than via
    # `index=True` on the fields: several are composite, and the names must
    # match the migration exactly so autogenerate stays quiet.
    __table_args__ = (
        Index("ux_transaction_reference", "reference", unique=True),
        Index("ix_transaction_group_id", "group_id"),
        Index("ix_transaction_user_created", "user_id", "created_at"),
        Index("ix_transaction_wallet_created", "wallet_id", "created_at"),
        Index("ix_transaction_agreement_id", "agreement_id"),
        Index("ix_transaction_type", "type"),
        Index("ix_transaction_status", "status"),
        Index(
            "ix_transaction_paystack_transaction_id", "paystack_transaction_id"
        ),
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    # --- ownership: the anchor for GET /transactions ---
    user_id: str = Field(foreign_key="user.id", nullable=False)
    # RESTRICT: deleting a wallet must never silently delete its ledger.
    wallet_id: str = Field(
        sa_column=Column(
            "wallet_id",
            String(),
            ForeignKey("wallet.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )

    # --- idempotency ---
    # `reference` is UNIQUE. It is the durable guarantee that no retry — client,
    # network or Paystack redelivery — can move money twice.
    reference: str = Field(sa_column=Column("reference", String(120), nullable=False))
    # Ties the two legs of a transfer together (escrow release out/in).
    group_id: str | None = Field(
        default=None, sa_column=Column("group_id", String(120), nullable=True)
    )

    # --- optional context: all nullable, a wallet funding has none of it ---
    agreement_id: str | None = Field(default=None, foreign_key="agreement.id")
    participant_id: str | None = Field(
        default=None, foreign_key="agreement_participant.id"
    )
    condition_id: str | None = Field(
        default=None,
        sa_column=Column(
            "condition_id",
            String(),
            ForeignKey("condition.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    paystack_transaction_id: str | None = Field(
        default=None, foreign_key="paystack_transaction.id"
    )
    counterparty_user_id: str | None = Field(default=None, foreign_key="user.id")

    # --- money: `amount` is always > 0, the deltas carry the sign ---
    amount: Decimal = Field(max_digits=12, decimal_places=2, nullable=False)
    currency: str = Field(default="NGN", max_length=3, nullable=False)
    available_delta: Decimal = Field(max_digits=12, decimal_places=2, nullable=False)
    escrow_delta: Decimal = Field(max_digits=12, decimal_places=2, nullable=False)
    balance_after: Decimal = Field(max_digits=12, decimal_places=2, nullable=False)
    escrow_after: Decimal = Field(max_digits=12, decimal_places=2, nullable=False)

    # --- classification ---
    # Explicit String columns: letting SQLModel infer these from the StrEnum
    # produces a native PG enum that stores member NAMES ("DEPOSIT") instead of
    # values ("deposit").
    type: LedgerEntryType = Field(
        sa_column=Column("type", String(32), nullable=False)
    )
    direction: LedgerDirection = Field(
        sa_column=Column("direction", String(10), nullable=False)
    )
    status: LedgerEntryStatus = Field(
        sa_column=Column("status", String(20), nullable=False)
    )

    description: str | None = Field(default=None, max_length=255)
    # `metadata` is reserved on SQLModel/SQLAlchemy, so the attribute is
    # `entry_metadata` but the DB column is named `metadata`.
    entry_metadata: dict[str, Any] | None = Field(
        default=None, sa_column=Column("metadata", JSONB, nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # No `lazy="selectin"` here — GET /transactions would otherwise fan out an
    # extra SELECT per row. The list endpoint serializes from plain columns.
    # Note: there are two FKs to user.id, so any future `User` relationship on
    # this model needs an explicit `foreign_keys=`.
    agreement: Optional["Agreement"] = Relationship(back_populates="transactions")
    participant: Optional["AgreementParticipant"] = Relationship(
        back_populates="transactions"
    )
