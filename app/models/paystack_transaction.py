import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any

from sqlmodel import SQLModel, Field, Column, String, DateTime
from sqlalchemy import Numeric, JSON


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class TransactionType(str, Enum):
    ESCROW_DEPOSIT = "ESCROW_DEPOSIT"  # Buyer paying in
    ESCROW_PAYOUT = "ESCROW_PAYOUT"  # Releasing to seller
    WITHDRAWAL = "WITHDRAWAL"  # User withdrawing to bank


class PaystackTransaction(SQLModel, table=True):
    __tablename__ = "paystack_transactions"

    # Internal IDs
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)

    # Core Transaction Identifiers
    reference: str = Field(unique=True, index=True, max_length=100)
    paystack_id: Optional[int] = Field(
        default=None, index=True
    )  # Paystack's internal ID from the webhook

    # Financials
    # Using SQLAlchemy's Numeric to ensure the DB stores exactly 2 decimal places
    amount: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    currency: str = Field(default="NGN", max_length=3)

    # State & Context
    status: TransactionStatus = Field(default=TransactionStatus.PENDING)
    transaction_type: TransactionType = Field(nullable=False)

    # Audit & Metadata
    payment_channel: Optional[str] = Field(
        default=None
    )  # e.g., 'card', 'bank_transfer'
    gateway_response: Optional[str] = Field(default=None)

    # Store the raw webhook data here. If a dispute happens, you have the exact payload.
    raw_webhook_data: Optional[Dict[str, Any]] = Field(
        default=dict, sa_column=Column(JSON)
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
