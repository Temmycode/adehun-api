from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.common.enums import LedgerDirection, LedgerEntryStatus, LedgerEntryType


class TransactionResponse(BaseModel):
    """One row in the user's financial history.

    Deliberately flat: embedding the participant or agreement object here would
    force a join (and an extra query per row) on a list endpoint. Clients that
    need agreement detail follow `agreement_id`.
    """

    id: str
    reference: str
    type: LedgerEntryType
    direction: LedgerDirection
    status: LedgerEntryStatus
    amount: Decimal
    currency: str
    balance_after: Decimal
    escrow_after: Decimal
    description: str | None = None
    agreement_id: str | None = None
    condition_id: str | None = None
    counterparty_user_id: str | None = None
    created_at: datetime
    processed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionSummaryResponse(BaseModel):
    total_credit: Decimal
    total_debit: Decimal
    credit_count: int
    debit_count: int


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    skip: int
    limit: int
    summary: TransactionSummaryResponse | None = None
