"""Read access to the wallet ledger.

READ-ONLY BY DESIGN. There are deliberately no write methods here. Ledger rows
are only ever created by `WalletRepository._apply_ledger_entry`, under a wallet
row lock, alongside the balance change they describe. Adding a write path to
this class would break the invariant documented in `wallet_repository`.

Every user-facing query is scoped by `user_id`. A user must never be able to
read another user's ledger.
"""

from datetime import datetime
from decimal import Decimal

from redis import Redis
from sqlalchemy import func
from sqlmodel import Session, select

from app.common.enums import LedgerDirection, LedgerEntryStatus, LedgerEntryType
from app.logging import get_logger
from app.models import Transaction
from app.redis import RedisClient

logger = get_logger(__name__)


class TransactionRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        super().__init__(redis_client)
        self.session = session

    def _filtered(
        self,
        statement,
        *,
        user_id: str,
        types: list[LedgerEntryType] | None = None,
        direction: LedgerDirection | None = None,
        status: LedgerEntryStatus | None = None,
        agreement_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        search: str | None = None,
    ):
        """Apply the shared filter set. `user_id` is never optional."""
        statement = statement.where(Transaction.user_id == user_id)

        if types:
            statement = statement.where(Transaction.type.in_(types))  # pyright: ignore[reportAttributeAccessIssue]
        if direction is not None:
            statement = statement.where(Transaction.direction == direction)
        if status is not None:
            statement = statement.where(Transaction.status == status)
        if agreement_id is not None:
            statement = statement.where(Transaction.agreement_id == agreement_id)
        if date_from is not None:
            statement = statement.where(Transaction.created_at >= date_from)
        if date_to is not None:
            statement = statement.where(Transaction.created_at <= date_to)
        if min_amount is not None:
            statement = statement.where(Transaction.amount >= min_amount)
        if max_amount is not None:
            statement = statement.where(Transaction.amount <= max_amount)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                Transaction.description.ilike(pattern)  # pyright: ignore[reportAttributeAccessIssue]
                | Transaction.reference.ilike(pattern)  # pyright: ignore[reportAttributeAccessIssue]
            )
        return statement

    def list_for_user(
        self, user_id: str, *, skip: int = 0, limit: int = 20, **filters
    ) -> list[Transaction]:
        """Every money movement for a user, newest first.

        Sorted by `(created_at DESC, id DESC)` — `created_at` alone can tie for
        the two legs of a transfer, which would make pagination unstable.
        Backed by `ix_transaction_user_created`.
        """
        statement = self._filtered(select(Transaction), user_id=user_id, **filters)
        results = self.session.exec(
            statement.order_by(
                Transaction.created_at.desc(),  # pyright: ignore[reportAttributeAccessIssue]
                Transaction.id.desc(),  # pyright: ignore[reportAttributeAccessIssue]
            )
            .offset(skip)
            .limit(limit)
        ).all()
        return list(results)

    def count_for_user(self, user_id: str, **filters) -> int:
        statement = self._filtered(
            select(func.count()).select_from(Transaction), user_id=user_id, **filters
        )
        return int(self.session.exec(statement).one())

    def summary_for_user(self, user_id: str, **filters) -> dict[str, Decimal | int]:
        """Totals in and out, for the header row on the history screen."""
        statement = self._filtered(
            select(
                Transaction.direction,
                func.coalesce(func.sum(Transaction.amount), 0),
                func.count(),
            ).select_from(Transaction),
            user_id=user_id,
            **filters,
        ).group_by(Transaction.direction)  # pyright: ignore[reportAttributeAccessIssue]

        totals: dict[str, Decimal | int] = {
            "total_credit": Decimal("0.00"),
            "total_debit": Decimal("0.00"),
            "credit_count": 0,
            "debit_count": 0,
        }
        for direction, total, count in self.session.exec(statement).all():
            if direction == LedgerDirection.CREDIT:
                totals["total_credit"] = Decimal(total)
                totals["credit_count"] = int(count)
            else:
                totals["total_debit"] = Decimal(total)
                totals["debit_count"] = int(count)
        return totals

    def get_by_id_for_user(
        self, transaction_id: str, user_id: str
    ) -> Transaction | None:
        return self.session.exec(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.user_id == user_id,
            )
        ).first()

    def get_by_reference(self, reference: str) -> Transaction | None:
        """Unscoped — for internal reconciliation only, never for a route."""
        return self.session.exec(
            select(Transaction).where(Transaction.reference == reference)
        ).first()

    def exists_reference(self, reference: str) -> bool:
        return (
            self.session.exec(
                select(Transaction.id).where(Transaction.reference == reference)
            ).first()
            is not None
        )

    def get_by_group(self, group_id: str) -> list[Transaction]:
        """Unscoped — for internal reconciliation only, never for a route."""
        return list(
            self.session.exec(
                select(Transaction).where(Transaction.group_id == group_id)
            ).all()
        )

    def agreement_has_entry_of_type(
        self, agreement_id: str, entry_type: LedgerEntryType
    ) -> bool:
        """Whether an agreement has a given ledger movement.

        This is how `is_funded` is derived — the ledger is the source of truth,
        so no extra agreement status value is needed.
        """
        return (
            self.session.exec(
                select(Transaction.id).where(
                    Transaction.agreement_id == agreement_id,
                    Transaction.type == entry_type,
                )
            ).first()
            is not None
        )

    def rollback(self) -> None:
        self.session.rollback()
