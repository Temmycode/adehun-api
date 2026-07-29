"""Wallet reads, and the single choke point through which money moves.

THE INVARIANT
-------------
A `Transaction` row is written ONLY when a balance actually moves. Its
`available_delta` / `escrow_delta` are the exact signed amounts applied.
Therefore, for every wallet, unconditionally:

    wallet.available_balance == SUM(available_delta)
    wallet.escrow_balance    == SUM(escrow_delta)

`status` is presentational and NEVER affects a balance. A reversal is a *new
row*, never a mutation of an old one.

Run this after any money operation; it must always return zero rows:

    SELECT w.id
    FROM wallet w LEFT JOIN transaction t ON t.wallet_id = w.id
    GROUP BY w.id
    HAVING w.available_balance <> COALESCE(SUM(t.available_delta), 0)
        OR w.escrow_balance    <> COALESCE(SUM(t.escrow_delta), 0);

LOCKING RULES
-------------
1. Table lock order is fixed: `paystack_transaction` -> `wallet` -> `transaction`.
   Never take a `paystack_transaction` lock while holding a `wallet` lock.
2. Within `wallet`, always lock in ascending `wallet.id` order, as separate
   single-row statements. (`ORDER BY ... FOR UPDATE` in one statement is not a
   guaranteed lock order across all plans; two `WHERE id = :x FOR UPDATE`
   statements are.)
3. `ensure_wallet()` COMMITS, so it releases locks. It must run before any lock
   is taken, never between a lock and a commit.
4. Nothing between `_lock_wallet*()` and `commit()` may call another repository
   method that commits.

TRANSACTION BOUNDARY
--------------------
`get_session()` yields one `Session` per request and FastAPI caches the
dependency, so every repository built for a request shares the same `Session`
and therefore the same DB transaction. `apply_entry` / `apply_transfer` are the
transaction boundary: anything a caller flushed earlier in the request is
committed by them, and rolled back by them on failure. That is what lets a
router flush an agreement change and have it commit atomically with the money.

Corollary: never call `apply_entry` twice in one request expecting
both-or-neither. Use `apply_transfer`.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from redis import Redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.common.enums import LedgerDirection, LedgerEntryStatus, LedgerEntryType
from app.exceptions import (
    BadRequestError,
    InsufficientEscrowBalanceError,
    InsufficientFundsError,
    WalletNotFoundError,
)
from app.logging import get_logger
from app.models import PaystackTransaction, Transaction, Wallet
from app.models.paystack_transaction import TransactionStatus, TransactionType
from app.redis import RedisClient

logger = get_logger(__name__)

_TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Cache keys
# ---------------------------------------------------------------------------


def _user_wallet_key(user_id: str) -> str:
    return f"user:{user_id}:wallet"


# ---------------------------------------------------------------------------
# The effects table
#
# A service passes a TYPE, never a delta. This is what makes "the balance
# cannot be touched arbitrarily" structurally true rather than a convention.
# ---------------------------------------------------------------------------

_LEDGER_EFFECTS: dict[LedgerEntryType, tuple[int, int]] = {
    #                                     (available, escrow)
    LedgerEntryType.DEPOSIT: (+1, 0),
    LedgerEntryType.ESCROW_LOCK: (-1, +1),
    LedgerEntryType.ESCROW_RELEASE_OUT: (0, -1),
    LedgerEntryType.ESCROW_RELEASE_IN: (+1, 0),
    LedgerEntryType.ESCROW_REFUND: (+1, -1),
    LedgerEntryType.WITHDRAWAL: (-1, 0),
    LedgerEntryType.WITHDRAWAL_REVERSAL: (+1, 0),
    LedgerEntryType.ADJUSTMENT_CREDIT: (+1, 0),
    LedgerEntryType.ADJUSTMENT_DEBIT: (-1, 0),
}

_LEDGER_DIRECTION: dict[LedgerEntryType, LedgerDirection] = {
    LedgerEntryType.DEPOSIT: LedgerDirection.CREDIT,
    LedgerEntryType.ESCROW_LOCK: LedgerDirection.DEBIT,
    LedgerEntryType.ESCROW_RELEASE_OUT: LedgerDirection.DEBIT,
    LedgerEntryType.ESCROW_RELEASE_IN: LedgerDirection.CREDIT,
    LedgerEntryType.ESCROW_REFUND: LedgerDirection.CREDIT,
    LedgerEntryType.WITHDRAWAL: LedgerDirection.DEBIT,
    LedgerEntryType.WITHDRAWAL_REVERSAL: LedgerDirection.CREDIT,
    LedgerEntryType.ADJUSTMENT_CREDIT: LedgerDirection.CREDIT,
    LedgerEntryType.ADJUSTMENT_DEBIT: LedgerDirection.DEBIT,
}


# ---------------------------------------------------------------------------
# Result / argument types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerResult:
    entry: Transaction
    wallet: Wallet
    replayed: bool


@dataclass(frozen=True)
class TransferResult:
    debit: Transaction
    credit: Transaction
    replayed: bool


@dataclass(frozen=True)
class LedgerLeg:
    """One side of a two-wallet transfer."""

    user_id: str
    entry_type: LedgerEntryType
    amount: Decimal
    description: str | None = None
    agreement_id: str | None = None
    participant_id: str | None = None
    condition_id: str | None = None
    paystack_transaction_id: str | None = None
    counterparty_user_id: str | None = None
    metadata: dict[str, Any] | None = field(default=None)

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "entry_type": self.entry_type,
            "amount": self.amount,
            "description": self.description,
            "agreement_id": self.agreement_id,
            "participant_id": self.participant_id,
            "condition_id": self.condition_id,
            "paystack_transaction_id": self.paystack_transaction_id,
            "counterparty_user_id": self.counterparty_user_id,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class WalletRepository(RedisClient):
    def __init__(self, session: Session, client: Redis | None):
        self.session = session
        super().__init__(client)

    # ------------------------------------------------------------------ #
    #  Reads                                                             #
    # ------------------------------------------------------------------ #

    def get_user_wallet(self, user_id: str) -> Wallet | None:
        """Return a user's wallet.

        READ ONLY. Never mutate the returned object — it is not locked, so a
        write through it would race. Balances are deliberately not cached: a
        stale balance is a correctness bug, not a performance win.
        """
        return self.session.exec(
            select(Wallet).where(Wallet.user_id == user_id)
        ).first()

    def get_wallet_by_id(self, wallet_id: str) -> Wallet | None:
        """READ ONLY. See `get_user_wallet`."""
        return self.session.exec(select(Wallet).where(Wallet.id == wallet_id)).first()

    def get_entry_by_reference(self, reference: str) -> Transaction | None:
        return self.session.exec(
            select(Transaction).where(Transaction.reference == reference)
        ).first()

    def get_entries_by_group(self, group_id: str) -> list[Transaction]:
        return list(
            self.session.exec(
                select(Transaction)
                .where(Transaction.group_id == group_id)
                .order_by(Transaction.reference)  # pyright: ignore[reportArgumentType]
            ).all()
        )

    # ------------------------------------------------------------------ #
    #  Wallet lifecycle                                                  #
    # ------------------------------------------------------------------ #

    def ensure_wallet(self, user_id: str) -> Wallet:
        """Return the user's wallet, creating it if absent.

        Race-safe and idempotent via ON CONFLICT DO NOTHING against the
        `uq_wallet_user_id` constraint. COMMITS — so per locking rule 3 this
        must run before any row lock is taken.
        """
        now = datetime.now(timezone.utc)
        statement = (
            pg_insert(Wallet.__table__)
            .values(
                id=str(uuid4()),
                user_id=user_id,
                available_balance=Decimal("0.00"),
                escrow_balance=Decimal("0.00"),
                currency="NGN",
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        # Core insert, so `.execute` rather than SQLModel's `.exec`.
        self.session.execute(statement)
        self.session.commit()
        return self.session.exec(select(Wallet).where(Wallet.user_id == user_id)).one()

    def _resolve_wallet_id(self, user_id: str) -> str:
        """Wallet id for a user, creating the wallet on miss.

        Unlocked, and may COMMIT via `ensure_wallet`. Call it at the very top of
        an operation, before anything is flushed.
        """
        wallet = self.get_user_wallet(user_id)
        if wallet is not None:
            return wallet.id
        return self.ensure_wallet(user_id).id

    def _lock_wallet(self, wallet_id: str) -> Wallet:
        """Take a row lock on one wallet."""
        wallet = self.session.exec(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        ).one_or_none()
        if wallet is None:
            raise WalletNotFoundError()
        return wallet

    def _lock_wallets(self, wallet_ids: Iterable[str]) -> dict[str, Wallet]:
        """Lock several wallets deadlock-free: ascending id, one statement each."""
        return {
            wallet_id: self._lock_wallet(wallet_id)
            for wallet_id in sorted(set(wallet_ids))
        }

    # ------------------------------------------------------------------ #
    #  The choke point                                                   #
    # ------------------------------------------------------------------ #

    def _apply_ledger_entry(
        self,
        wallet: Wallet,
        *,
        user_id: str,
        entry_type: LedgerEntryType,
        amount: Decimal,
        reference: str,
        status: LedgerEntryStatus = LedgerEntryStatus.COMPLETED,
        description: str | None = None,
        group_id: str | None = None,
        agreement_id: str | None = None,
        participant_id: str | None = None,
        condition_id: str | None = None,
        paystack_transaction_id: str | None = None,
        counterparty_user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Transaction:
        """THE ONLY PLACE A WALLET BALANCE MAY CHANGE.

        Precondition: `wallet` was returned by `_lock_wallet()` / `_lock_wallets()`
        in the CURRENT transaction. Does NOT commit — the public wrappers own
        the commit.
        """
        if amount is None or amount <= 0:
            raise BadRequestError("Amount must be greater than zero")
        if amount != amount.quantize(_TWO_PLACES):
            raise BadRequestError("Amount may not have more than 2 decimal places")

        available_sign, escrow_sign = _LEDGER_EFFECTS[entry_type]
        available_delta = amount * available_sign
        escrow_delta = amount * escrow_sign

        new_available = wallet.available_balance + available_delta
        new_escrow = wallet.escrow_balance + escrow_delta

        if new_available < 0:
            raise InsufficientFundsError(
                f"Insufficient available balance: have {wallet.available_balance}, "
                f"need {amount}"
            )
        if new_escrow < 0:
            raise InsufficientEscrowBalanceError(
                f"Insufficient escrow balance: have {wallet.escrow_balance}, "
                f"need {amount}"
            )

        now = datetime.now(timezone.utc)
        entry = Transaction(
            user_id=user_id,
            wallet_id=wallet.id,
            reference=reference,
            group_id=group_id,
            amount=amount,
            currency=wallet.currency,
            available_delta=available_delta,
            escrow_delta=escrow_delta,
            balance_after=new_available,
            escrow_after=new_escrow,
            type=entry_type,
            direction=_LEDGER_DIRECTION[entry_type],
            status=status,
            description=description,
            entry_metadata=metadata,
            agreement_id=agreement_id,
            participant_id=participant_id,
            condition_id=condition_id,
            paystack_transaction_id=paystack_transaction_id,
            counterparty_user_id=counterparty_user_id,
            created_at=now,
            processed_at=now if status is LedgerEntryStatus.COMPLETED else None,
        )

        wallet.available_balance = new_available
        wallet.escrow_balance = new_escrow
        wallet.updated_at = now

        self.session.add(entry)
        self.session.add(wallet)
        return entry

    # ------------------------------------------------------------------ #
    #  Public wrappers — the only money entry points a service may call  #
    # ------------------------------------------------------------------ #

    def apply_entry(
        self,
        *,
        user_id: str,
        entry_type: LedgerEntryType,
        amount: Decimal,
        reference: str,
        status: LedgerEntryStatus = LedgerEntryStatus.COMPLETED,
        description: str | None = None,
        group_id: str | None = None,
        agreement_id: str | None = None,
        participant_id: str | None = None,
        condition_id: str | None = None,
        paystack_transaction_id: str | None = None,
        counterparty_user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerResult:
        """Move money on a single wallet, atomically and idempotently.

        Replaying the same `reference` returns the original entry untouched.
        Commits — including anything the caller flushed earlier in the request.
        """
        existing = self.get_entry_by_reference(reference)
        if existing is not None:
            return self._replay(existing)

        # May COMMIT (ensure_wallet), so it happens before any lock is taken.
        wallet_id = self._resolve_wallet_id(user_id)

        try:
            wallet = self._lock_wallet(wallet_id)
            entry = self._apply_ledger_entry(
                wallet,
                user_id=user_id,
                entry_type=entry_type,
                amount=amount,
                reference=reference,
                status=status,
                description=description,
                group_id=group_id,
                agreement_id=agreement_id,
                participant_id=participant_id,
                condition_id=condition_id,
                paystack_transaction_id=paystack_transaction_id,
                counterparty_user_id=counterparty_user_id,
                metadata=metadata,
            )
            self.session.commit()
        except IntegrityError:
            # A concurrent writer won the race on ux_transaction_reference.
            self.session.rollback()
            existing = self.get_entry_by_reference(reference)
            if existing is None:
                raise  # a genuine constraint violation, not a replay
            logger.info(
                "ledger entry replayed after unique-reference conflict",
                extra={"reference": reference, "user_id": user_id},
            )
            return self._replay(existing)
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(entry)
        self.session.refresh(wallet)
        self._cache_delete(_user_wallet_key(user_id))

        logger.info(
            "ledger entry applied",
            extra={
                "reference": reference,
                "user_id": user_id,
                "type": entry_type.value,
                "amount": str(amount),
                "balance_after": str(wallet.available_balance),
                "escrow_after": str(wallet.escrow_balance),
            },
        )
        return LedgerResult(entry=entry, wallet=wallet, replayed=False)

    def apply_transfer(
        self, *, group_id: str, debit: LedgerLeg, credit: LedgerLeg
    ) -> TransferResult:
        """Move money between two wallets in one DB transaction.

        Both legs share `group_id`; their references are derived from it, so a
        replay of either half collapses to a no-op.
        """
        debit_reference = f"{group_id}:out"
        credit_reference = f"{group_id}:in"

        existing = self.get_entries_by_group(group_id)
        if len(existing) == 2:
            return self._replay_transfer(existing, debit_reference)

        # Both may COMMIT (ensure_wallet), so both happen before any lock.
        debit_wallet_id = self._resolve_wallet_id(debit.user_id)
        credit_wallet_id = self._resolve_wallet_id(credit.user_id)

        try:
            # Sorted ascending by id inside _lock_wallets -> no deadlock when two
            # transfers touch the same pair of wallets in opposite directions.
            wallets = self._lock_wallets([debit_wallet_id, credit_wallet_id])

            # Self-transfer: when both legs are the same wallet, sorted(set(...))
            # yields one id and both legs get the SAME ORM instance. The second
            # _apply_ledger_entry then reads the already-mutated balance, so the
            # arithmetic is correct by construction. Do not "fix" this.
            debit_entry = self._apply_ledger_entry(
                wallets[debit_wallet_id],
                reference=debit_reference,
                group_id=group_id,
                **debit.as_kwargs(),
            )
            credit_entry = self._apply_ledger_entry(
                wallets[credit_wallet_id],
                reference=credit_reference,
                group_id=group_id,
                **credit.as_kwargs(),
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.get_entries_by_group(group_id)
            if len(existing) != 2:
                raise
            logger.info(
                "transfer replayed after unique-reference conflict",
                extra={"group_id": group_id},
            )
            return self._replay_transfer(existing, debit_reference)
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(debit_entry)
        self.session.refresh(credit_entry)
        self._cache_delete(
            _user_wallet_key(debit.user_id), _user_wallet_key(credit.user_id)
        )

        logger.info(
            "ledger transfer applied",
            extra={
                "group_id": group_id,
                "debit_user_id": debit.user_id,
                "credit_user_id": credit.user_id,
                "amount": str(debit.amount),
            },
        )
        return TransferResult(debit=debit_entry, credit=credit_entry, replayed=False)

    def _replay(self, entry: Transaction) -> LedgerResult:
        wallet = self.get_wallet_by_id(entry.wallet_id)
        if wallet is None:
            raise WalletNotFoundError()
        return LedgerResult(entry=entry, wallet=wallet, replayed=True)

    def _replay_transfer(
        self, entries: list[Transaction], debit_reference: str
    ) -> TransferResult:
        debit = next(e for e in entries if e.reference == debit_reference)
        credit = next(e for e in entries if e.reference != debit_reference)
        return TransferResult(debit=debit, credit=credit, replayed=True)

    def mark_entry_status(
        self,
        reference: str,
        status: LedgerEntryStatus,
        *,
        processed_at: datetime | None = None,
        commit: bool = True,
    ) -> Transaction | None:
        """Update a ledger row's presentational status.

        Never touches a balance — see the module invariant. Use `commit=False`
        to have the change ride along with a following `apply_entry` commit.
        """
        entry = self.get_entry_by_reference(reference)
        if entry is None:
            return None

        entry.status = status
        if processed_at is not None:
            entry.processed_at = processed_at
        elif status is LedgerEntryStatus.COMPLETED and entry.processed_at is None:
            entry.processed_at = datetime.now(timezone.utc)

        self.session.add(entry)
        if commit:
            self.session.commit()
            self.session.refresh(entry)
        return entry

    # ------------------------------------------------------------------ #
    #  Paystack transaction records                                      #
    # ------------------------------------------------------------------ #

    def create_paystack_transaction(
        self,
        *,
        user_id: str,
        reference: str,
        amount: Decimal,
        transaction_type: TransactionType,
        status: TransactionStatus = TransactionStatus.PENDING,
        payment_channel: str | None = None,
        recipient_code: str | None = None,
        bank_account_id: str | None = None,
        commit: bool = True,
    ) -> PaystackTransaction:
        """Record an intent to move money through Paystack."""
        paystack_transaction = PaystackTransaction(
            user_id=user_id,
            reference=reference,
            amount=amount,
            transaction_type=transaction_type,
            status=status,
            payment_channel=payment_channel,
            recipient_code=recipient_code,
            bank_account_id=bank_account_id,
        )
        self.session.add(paystack_transaction)
        if commit:
            self.session.commit()
            self.session.refresh(paystack_transaction)
        else:
            self.session.flush()
        return paystack_transaction

    def save_paystack_transaction(
        self, paystack_transaction: PaystackTransaction, *, commit: bool = True
    ) -> PaystackTransaction:
        self.session.add(paystack_transaction)
        if commit:
            self.session.commit()
            self.session.refresh(paystack_transaction)
        return paystack_transaction

    def get_paystack_transaction(
        self, transaction_reference: str
    ) -> PaystackTransaction | None:
        """Fetch and LOCK a Paystack transaction row.

        Per locking rule 1 this is the FIRST lock in any webhook flow — never
        take it while already holding a wallet lock.
        """
        return self.session.exec(
            select(PaystackTransaction)
            .where(PaystackTransaction.reference == transaction_reference)
            .with_for_update()
        ).first()

    def get_paystack_transaction_for_user(
        self, reference: str, user_id: str
    ) -> PaystackTransaction | None:
        """Unlocked, user-scoped read for the withdrawal status endpoint."""
        return self.session.exec(
            select(PaystackTransaction).where(
                PaystackTransaction.reference == reference,
                PaystackTransaction.user_id == user_id,
            )
        ).first()

    def rollback(self) -> None:
        self.session.rollback()
