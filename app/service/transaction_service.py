"""Read-side of the wallet ledger."""

from datetime import datetime
from decimal import Decimal

from app.common.enums import LedgerDirection, LedgerEntryStatus, LedgerEntryType
from app.exceptions import TransactionNotFoundError
from app.logging import get_logger
from app.repository.transaction_repository import TransactionRepository
from app.schemas.transactions_schema import (
    TransactionListResponse,
    TransactionResponse,
    TransactionSummaryResponse,
)

logger = get_logger(__name__)


class TransactionService:
    def __init__(self, transaction_repo: TransactionRepository):
        self.transaction_repo = transaction_repo

    def get_user_transactions(
        self,
        user_id: str,
        *,
        skip: int = 0,
        limit: int = 20,
        types: list[LedgerEntryType] | None = None,
        direction: LedgerDirection | None = None,
        status: LedgerEntryStatus | None = None,
        agreement_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        search: str | None = None,
    ) -> TransactionListResponse:
        """Every money movement for a user: deposits, escrow, payouts, reversals."""
        filters = {
            "types": types,
            "direction": direction,
            "status": status,
            "agreement_id": agreement_id,
            "date_from": date_from,
            "date_to": date_to,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "search": search,
        }

        entries = self.transaction_repo.list_for_user(
            user_id, skip=skip, limit=limit, **filters
        )
        total = self.transaction_repo.count_for_user(user_id, **filters)
        summary = self.transaction_repo.summary_for_user(user_id, **filters)

        return TransactionListResponse(
            transactions=[TransactionResponse.model_validate(e) for e in entries],
            total=total,
            skip=skip,
            limit=limit,
            summary=TransactionSummaryResponse(**summary),  # pyright: ignore[reportArgumentType]
        )

    def get_transaction(self, transaction_id: str, user_id: str) -> TransactionResponse:
        """Fetch one entry, scoped to its owner."""
        entry = self.transaction_repo.get_by_id_for_user(transaction_id, user_id)
        if entry is None:
            raise TransactionNotFoundError()
        return TransactionResponse.model_validate(entry)

    def get_summary(self, user_id: str) -> TransactionSummaryResponse:
        return TransactionSummaryResponse(
            **self.transaction_repo.summary_for_user(user_id)  # pyright: ignore[reportArgumentType]
        )

    def is_agreement_funded(self, agreement_id: str) -> bool:
        """Derived from the ledger — no `funded` agreement status is needed."""
        return self.transaction_repo.agreement_has_entry_of_type(
            agreement_id, LedgerEntryType.ESCROW_LOCK
        )

    def is_agreement_released(self, agreement_id: str) -> bool:
        return self.transaction_repo.exists_reference(f"esc_rel_{agreement_id}:out")
