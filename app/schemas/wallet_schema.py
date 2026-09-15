from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.core.validators import reject_sub_kobo

FundingChannel = Literal["card", "bank", "ussd", "bank_transfer", "qr", "mobile_money"]

# Kept as an alias so existing imports keep working.
_reject_sub_kobo = reject_sub_kobo


class WalletCreate(BaseModel):
    """Body for POST /wallet/fund."""

    amount: Decimal = Field(
        gt=0,
        le=settings.wallet_fund_max_amount,
        description="Amount in naira, max 2 decimal places",
    )
    channel: FundingChannel = "card"

    _validate_amount = field_validator("amount")(reject_sub_kobo)


class FundInitResponse(BaseModel):
    """Everything a client needs to start a payment.

    `authorization_url` is what the web client redirects to; mobile uses
    `access_code` with the Paystack SDK.
    """

    reference: str
    access_code: str
    authorization_url: str | None = None
    amount: Decimal


class WalletBalanceResponse(BaseModel):
    available_balance: Decimal
    escrow_balance: Decimal
    total_balance: Decimal
    currency: str
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class WithdrawalCreate(BaseModel):
    """Body for POST /wallet/withdraw."""

    amount: Decimal = Field(gt=0, description="Amount in naira, max 2 decimal places")
    bank_account_id: str | None = Field(
        default=None,
        description="Defaults to the user's default bank account when omitted",
    )

    _validate_amount = field_validator("amount")(reject_sub_kobo)


class WithdrawalResponse(BaseModel):
    reference: str
    amount: Decimal
    currency: str
    status: str
    bank_account_id: str | None = None
    account_number: str | None = None
    bank_name: str | None = None
    available_balance: Decimal | None = None
    failure_reason: str | None = None
    created_at: datetime | None = None
