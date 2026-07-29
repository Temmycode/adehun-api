from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, Index, String, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .user import User


class BankAccount(SQLModel, table=True):
    """A payout destination, backed by a Paystack transfer recipient.

    SECURITY: `account_name` is never taken from the client. It always comes
    from Paystack's `resolve_account_number`, otherwise a user could label
    someone else's account as their own.
    """

    __tablename__ = "bank_account"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_bank_account_user_id", "user_id"),
        Index("ix_bank_account_recipient_code", "recipient_code", unique=True),
        # A user cannot save the same account twice while it is active...
        Index(
            "ux_bank_account_user_bank_acct",
            "user_id",
            "bank_code",
            "account_number",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        # ...and can have at most one default account.
        Index(
            "ux_bank_account_one_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default AND is_active"),
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", nullable=False)

    account_number: str = Field(max_length=20, nullable=False)
    bank_code: str = Field(max_length=10, nullable=False)
    bank_name: str = Field(max_length=120, nullable=False)
    account_name: str = Field(max_length=120, nullable=False)
    recipient_code: str = Field(
        sa_column=Column("recipient_code", String(100), nullable=False)
    )
    currency: str = Field(default="NGN", max_length=3, nullable=False)
    is_default: bool = Field(default=False, nullable=False)
    is_active: bool = Field(default=True, nullable=False)

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

    user: Optional["User"] = Relationship(back_populates="bank_accounts")
