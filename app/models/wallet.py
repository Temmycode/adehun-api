from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .user import User


class Wallet(SQLModel, table=True):
    """A user's money, in two buckets.

    `available_balance` is spendable — it can be withdrawn to a bank or locked
    into an agreement. `escrow_balance` is committed to an agreement and cannot
    be touched until the agreement releases or refunds it.

    Balances are ONLY ever mutated by `WalletRepository._apply_ledger_entry`,
    under a `SELECT ... FOR UPDATE` row lock, alongside the `Transaction` ledger
    row that records the movement. The CHECK constraints below are the backstop
    if anything ever bypasses that path.
    """

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_wallet_user_id"),
        CheckConstraint(
            "available_balance >= 0", name="ck_wallet_available_non_negative"
        ),
        CheckConstraint("escrow_balance >= 0", name="ck_wallet_escrow_non_negative"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", nullable=False)
    available_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2, nullable=False
    )
    escrow_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=12, decimal_places=2, nullable=False
    )
    currency: str = Field(default="NGN", max_length=3, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

    user: "User" = Relationship(back_populates="wallet")
