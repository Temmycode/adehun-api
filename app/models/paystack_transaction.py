import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional  # noqa: UP035

from sqlalchemy import JSON, BigInteger, Numeric, String
from sqlmodel import Column, DateTime, Field, SQLModel


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class TransactionType(str, Enum):
    ESCROW_DEPOSIT = "ESCROW_DEPOSIT"  # Buyer paying in
    ESCROW_PAYOUT = "ESCROW_PAYOUT"  # Releasing to seller
    ESCROW_REFUND = "ESCROW_REFUND"  # Returning escrow to the depositor
    WITHDRAWAL = "WITHDRAWAL"  # User withdrawing to bank


class PaystackTransaction(SQLModel, table=True):
    __tablename__ = "paystack_transaction"
    # Internal IDs
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)

    # Core Transaction Identifiers
    reference: str = Field(unique=True, index=True, max_length=100)
    # Paystack's internal ID from the webhook. BigInteger — these already
    # exceed 2**31, so a plain Integer column would overflow.
    paystack_id: "Optional[int]" = Field(
        default=None, sa_column=Column(BigInteger, nullable=True, index=True)
    )

    # Financials
    # Using SQLAlchemy's Numeric to ensure the DB stores exactly 2 decimal places
    amount: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    currency: str = Field(default="NGN", max_length=3)

    # State & Context
    # Explicit String columns — SQLModel would otherwise infer a native PG enum,
    # which is not what the table actually has.
    status: TransactionStatus = Field(
        default=TransactionStatus.PENDING,
        sa_column=Column("status", String(50), nullable=False),
    )
    transaction_type: TransactionType = Field(
        sa_column=Column("transaction_type", String(50), nullable=False)
    )

    # Transfers (payouts / withdrawals)
    transfer_code: Optional[str] = Field(
        default=None, sa_column=Column("transfer_code", String(100), index=True)
    )
    recipient_code: Optional[str] = Field(default=None, max_length=100)
    bank_account_id: Optional[str] = Field(default=None, foreign_key="bank_account.id")
    failure_reason: Optional[str] = Field(default=None, max_length=255)

    # Audit & Metadata
    payment_channel: Optional[str] = Field(
        default=None
    )  # e.g., 'card', 'bank_transfer'
    gateway_response: Optional[str] = Field(default=None)

    # Store the raw webhook data here. If a dispute happens, you have the exact payload.
    raw_webhook_data: Optional[Dict[str, Any]] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )

    # Timestamps
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
