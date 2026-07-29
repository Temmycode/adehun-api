"""Wallet business logic.

Balances are never mutated here. Every movement goes through
`WalletRepository.apply_entry` / `apply_transfer`, which take the row lock,
write the ledger row and commit atomically. This service only decides *what*
should move and *why*.
"""

import uuid
from decimal import Decimal

from app.common.enums import LedgerEntryStatus, LedgerEntryType
from app.config import settings
from app.exceptions import (
    BadRequestError,
    BankAccountNotFoundError,
    TransactionNotFoundError,
    WithdrawalNotAllowedError,
)
from app.logging import get_logger
from app.models import BankAccount
from app.models.paystack_transaction import TransactionStatus, TransactionType
from app.repository.bank_account_repository import BankAccountRepository
from app.repository.wallet_repository import (
    LedgerLeg,
    LedgerResult,
    TransferResult,
    WalletRepository,
)
from app.schemas.wallet_schema import (
    FundInitResponse,
    WalletBalanceResponse,
    WalletCreate,
    WithdrawalCreate,
    WithdrawalResponse,
)
from app.service.paystack_client import (
    PaystackDuplicateReferenceError,
    PaystackError,
    PaystackTimeoutError,
    PaystackValidationError,
    paystack_client,
)

logger = get_logger(__name__)


def generate_fund_reference(user_id: str) -> str:
    """Paystack references allow alphanumerics plus `-`, `.` and `=`."""
    return f"ESC-{user_id[:8]}-{uuid.uuid4().hex[:12]}"


def generate_withdrawal_reference(user_id: str) -> str:
    return f"WD-{user_id[:8]}-{uuid.uuid4().hex[:12]}"


def to_kobo(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("0.01")) * 100)


def status_name(status) -> str:
    """Lowercase status name, whether it arrived as an enum or a plain string.

    `paystack_transaction.status` is a `String` column, so SQLAlchemy hands back
    a bare `str` on a loaded row and a `TransactionStatus` on one built in
    memory. `str(enum)` would give "TransactionStatus.PENDING", hence `.value`.
    """
    return str(getattr(status, "value", status)).lower()


class WalletService:
    def __init__(
        self,
        wallet_repo: WalletRepository,
        bank_account_repo: BankAccountRepository | None = None,
    ):
        self.wallet_repo = wallet_repo
        self.bank_account_repo = bank_account_repo

    # ------------------------------------------------------------------ #
    #  Reads                                                             #
    # ------------------------------------------------------------------ #

    def get_balance(self, user_id: str) -> WalletBalanceResponse:
        """Current balances, creating the wallet on first read."""
        wallet = self.wallet_repo.ensure_wallet(user_id)
        return WalletBalanceResponse(
            available_balance=wallet.available_balance,
            escrow_balance=wallet.escrow_balance,
            total_balance=wallet.available_balance + wallet.escrow_balance,
            currency=wallet.currency,
            updated_at=wallet.updated_at,
        )

    def get_wallet_state_for_ws(self, user_id: str) -> dict:
        """The frame pushed when a websocket connects."""
        wallet = self.wallet_repo.ensure_wallet(user_id)
        return {
            "type": "WALLET_STATE",
            "available_balance": float(wallet.available_balance),
            "escrow_balance": float(wallet.escrow_balance),
            "total_balance": float(wallet.available_balance + wallet.escrow_balance),
            "currency": wallet.currency,
        }

    # ------------------------------------------------------------------ #
    #  Funding                                                           #
    # ------------------------------------------------------------------ #

    async def request_wallet_fund(
        self, user_id: str, user_email: str, wallet_data: WalletCreate
    ) -> FundInitResponse:
        """Start a Paystack payment.

        No money moves here. The wallet is credited only when the
        `charge.success` webhook arrives and is verified.
        """
        reference = generate_fund_reference(user_id)

        data = await paystack_client.initialize_transaction(
            email=user_email,
            amount_kobo=to_kobo(wallet_data.amount),
            reference=reference,
            channels=[wallet_data.channel],
            callback_url=settings.paystack_callback_url,
        )

        self.wallet_repo.create_paystack_transaction(
            user_id=user_id,
            reference=reference,
            amount=wallet_data.amount,
            transaction_type=TransactionType.ESCROW_DEPOSIT,
            payment_channel=wallet_data.channel,
        )

        logger.info(
            "wallet funding initialised",
            extra={
                "user_id": user_id,
                "reference": reference,
                "amount": str(wallet_data.amount),
                "channel": wallet_data.channel,
            },
        )
        return FundInitResponse(
            reference=reference,
            access_code=data["access_code"],
            authorization_url=data.get("authorization_url"),
            amount=wallet_data.amount,
        )

    # ------------------------------------------------------------------ #
    #  Escrow                                                            #
    # ------------------------------------------------------------------ #

    def lock_escrow(
        self,
        *,
        user_id: str,
        amount: Decimal,
        agreement_id: str,
        participant_id: str | None = None,
        counterparty_user_id: str | None = None,
        description: str | None = None,
    ) -> LedgerResult:
        """Move a depositor's money from available into escrow."""
        return self.wallet_repo.apply_entry(
            user_id=user_id,
            entry_type=LedgerEntryType.ESCROW_LOCK,
            amount=amount,
            reference=f"esc_lock_{agreement_id}",
            agreement_id=agreement_id,
            participant_id=participant_id,
            counterparty_user_id=counterparty_user_id,
            description=description or "Escrow funding",
        )

    def release_escrow(
        self,
        *,
        agreement_id: str,
        depositor_user_id: str,
        beneficiary_user_id: str,
        amount: Decimal,
        description: str | None = None,
    ) -> TransferResult:
        """Hand escrowed money to the beneficiary.

        Both legs commit together, and the `esc_rel_` group id makes a repeat
        call a no-op — which is what lets the automatic release be retried by
        the manual fallback endpoint without risk.
        """
        label = description or "Escrow release"
        return self.wallet_repo.apply_transfer(
            group_id=f"esc_rel_{agreement_id}",
            debit=LedgerLeg(
                user_id=depositor_user_id,
                entry_type=LedgerEntryType.ESCROW_RELEASE_OUT,
                amount=amount,
                agreement_id=agreement_id,
                counterparty_user_id=beneficiary_user_id,
                description=label,
            ),
            credit=LedgerLeg(
                user_id=beneficiary_user_id,
                entry_type=LedgerEntryType.ESCROW_RELEASE_IN,
                amount=amount,
                agreement_id=agreement_id,
                counterparty_user_id=depositor_user_id,
                description=label,
            ),
        )

    def refund_escrow(
        self,
        *,
        agreement_id: str,
        depositor_user_id: str,
        amount: Decimal,
        description: str | None = None,
    ) -> LedgerResult:
        """Return escrowed money to the depositor.

        No endpoint exposes this yet — there is no admin/role concept in the
        codebase to authorise it. It exists so the ledger path is in place and
        ops can drive it deliberately.
        """
        return self.wallet_repo.apply_entry(
            user_id=depositor_user_id,
            entry_type=LedgerEntryType.ESCROW_REFUND,
            amount=amount,
            reference=f"esc_ref_{agreement_id}",
            agreement_id=agreement_id,
            description=description or "Escrow refund",
        )

    # ------------------------------------------------------------------ #
    #  Withdrawal                                                        #
    # ------------------------------------------------------------------ #

    def _resolve_bank_account(
        self, user_id: str, bank_account_id: str | None
    ) -> BankAccount:
        if self.bank_account_repo is None:  # pragma: no cover - wiring guard
            raise WithdrawalNotAllowedError("Withdrawals are not configured")

        if bank_account_id:
            account = self.bank_account_repo.get_for_user(bank_account_id, user_id)
            if account is None:
                raise BankAccountNotFoundError()
            return account

        account = self.bank_account_repo.get_default_for_user(user_id)
        if account is None:
            raise BankAccountNotFoundError(
                "No default bank account. Add one or pass bank_account_id."
            )
        return account

    async def request_withdrawal(
        self, user_id: str, payload: WithdrawalCreate
    ) -> WithdrawalResponse:
        """Pay money out to a bank account.

        ORDERING IS THE WHOLE POINT — debit first, then call Paystack. Never
        initiate a transfer for money that has not already been removed from the
        spendable balance.
        """
        if not settings.paystack_transfers_enabled:
            raise WithdrawalNotAllowedError(
                "Withdrawals are temporarily unavailable"
            )
        if payload.amount < settings.withdrawal_min_amount:
            raise BadRequestError(
                f"Minimum withdrawal is {settings.withdrawal_min_amount}"
            )
        if payload.amount > settings.withdrawal_max_amount:
            raise BadRequestError(
                f"Maximum withdrawal is {settings.withdrawal_max_amount}"
            )

        account = self._resolve_bank_account(user_id, payload.bank_account_id)
        reference = generate_withdrawal_reference(user_id)

        # 1. Record the intent (uncommitted — apply_entry commits it with the debit).
        paystack_transaction = self.wallet_repo.create_paystack_transaction(
            user_id=user_id,
            reference=reference,
            amount=payload.amount,
            transaction_type=TransactionType.WITHDRAWAL,
            recipient_code=account.recipient_code,
            bank_account_id=account.id,
            commit=False,
        )

        # 2. Debit now. Raises InsufficientFundsError -> 409, nothing persisted.
        result = self.wallet_repo.apply_entry(
            user_id=user_id,
            entry_type=LedgerEntryType.WITHDRAWAL,
            amount=payload.amount,
            reference=f"wd_{reference}",
            status=LedgerEntryStatus.PENDING,
            paystack_transaction_id=paystack_transaction.id,
            description=f"Withdrawal to {account.bank_name} {account.account_number}",
            metadata={
                "bank_account_id": account.id,
                "bank_code": account.bank_code,
                "account_number": account.account_number,
            },
        )

        # 3. Only now does money leave.
        try:
            data = await paystack_client.initiate_transfer(
                amount_kobo=to_kobo(payload.amount),
                recipient_code=account.recipient_code,
                reference=reference,
                reason="Wallet withdrawal",
            )
        except (PaystackTimeoutError, PaystackDuplicateReferenceError) as err:
            # Outcome UNKNOWN — the transfer may well have gone through. Do NOT
            # reverse. Leave both records PENDING for the transfer.* webhook (or
            # a later verify_transfer) to reconcile.
            logger.warning(
                "withdrawal outcome unknown, leaving pending for reconciliation",
                extra={
                    "user_id": user_id,
                    "reference": reference,
                    "error": type(err).__name__,
                },
            )
            return self._withdrawal_response(
                paystack_transaction, account, result.wallet.available_balance
            )
        except (PaystackValidationError, PaystackError) as err:
            # Definitively rejected, so nothing left our account. Safe to reverse.
            logger.warning(
                "withdrawal rejected by provider, reversing debit",
                extra={
                    "user_id": user_id,
                    "reference": reference,
                    "provider_message": err.message,
                },
            )
            self._reverse_withdrawal(
                reference=reference,
                user_id=user_id,
                amount=payload.amount,
                reason=err.message,
            )
            raise

        paystack_transaction.transfer_code = data.get("transfer_code")
        paystack_transaction.paystack_id = data.get("id")
        self.wallet_repo.save_paystack_transaction(paystack_transaction)

        logger.info(
            "withdrawal initiated",
            extra={
                "user_id": user_id,
                "reference": reference,
                "amount": str(payload.amount),
                "transfer_code": paystack_transaction.transfer_code,
            },
        )
        return self._withdrawal_response(
            paystack_transaction, account, result.wallet.available_balance
        )

    def _reverse_withdrawal(
        self, *, reference: str, user_id: str, amount: Decimal, reason: str
    ) -> None:
        """Undo a debit whose transfer was definitively refused."""
        paystack_transaction = self.wallet_repo.get_paystack_transaction(reference)
        if paystack_transaction is not None:
            paystack_transaction.status = TransactionStatus.FAILED
            paystack_transaction.failure_reason = reason[:255]
            self.wallet_repo.save_paystack_transaction(
                paystack_transaction, commit=False
            )

        self.wallet_repo.mark_entry_status(
            f"wd_{reference}", LedgerEntryStatus.REVERSED, commit=False
        )
        self.wallet_repo.apply_entry(
            user_id=user_id,
            entry_type=LedgerEntryType.WITHDRAWAL_REVERSAL,
            amount=amount,
            reference=f"wdrev_{reference}",
            description="Withdrawal could not be sent",
            metadata={"reason": reason[:255]},
        )

    def _withdrawal_response(
        self,
        paystack_transaction,
        account: BankAccount,
        available_balance: Decimal | None = None,
    ) -> WithdrawalResponse:
        return WithdrawalResponse(
            reference=paystack_transaction.reference,
            amount=paystack_transaction.amount,
            currency=paystack_transaction.currency,
            status=status_name(paystack_transaction.status),
            bank_account_id=account.id,
            account_number=account.account_number,
            bank_name=account.bank_name,
            available_balance=available_balance,
            failure_reason=paystack_transaction.failure_reason,
            created_at=paystack_transaction.created_at,
        )

    async def get_withdrawal(self, user_id: str, reference: str) -> WithdrawalResponse:
        """Status of a withdrawal, reconciling lazily if it has been stuck.

        A transfer whose initiate call timed out sits PENDING until the webhook
        lands. If a client asks about one, ask Paystack directly rather than
        leaving the user staring at "pending".
        """
        paystack_transaction = self.wallet_repo.get_paystack_transaction_for_user(
            reference, user_id
        )
        if paystack_transaction is None:
            raise TransactionNotFoundError("Withdrawal not found")

        if paystack_transaction.status == TransactionStatus.PENDING:
            await self._reconcile_pending_withdrawal(paystack_transaction)

        account = None
        if self.bank_account_repo is not None and paystack_transaction.bank_account_id:
            account = self.bank_account_repo.get_for_user(
                paystack_transaction.bank_account_id, user_id
            )

        wallet = self.wallet_repo.get_user_wallet(user_id)
        return WithdrawalResponse(
            reference=paystack_transaction.reference,
            amount=paystack_transaction.amount,
            currency=paystack_transaction.currency,
            status=status_name(paystack_transaction.status),
            bank_account_id=paystack_transaction.bank_account_id,
            account_number=account.account_number if account else None,
            bank_name=account.bank_name if account else None,
            available_balance=wallet.available_balance if wallet else None,
            failure_reason=paystack_transaction.failure_reason,
            created_at=paystack_transaction.created_at,
        )

    async def _reconcile_pending_withdrawal(self, paystack_transaction) -> None:
        """Best effort — a failure here must not break the status read."""
        try:
            data = await paystack_client.verify_transfer(
                paystack_transaction.reference
            )
        except PaystackError:
            logger.info(
                "could not verify pending transfer",
                extra={"reference": paystack_transaction.reference},
                exc_info=True,
            )
            return

        status = str(data.get("status") or "").lower()
        if status == "success":
            paystack_transaction.status = TransactionStatus.SUCCESS
            paystack_transaction.transfer_code = data.get("transfer_code")
            self.wallet_repo.save_paystack_transaction(
                paystack_transaction, commit=False
            )
            self.wallet_repo.mark_entry_status(
                f"wd_{paystack_transaction.reference}", LedgerEntryStatus.COMPLETED
            )
        elif status in {"failed", "reversed", "abandoned"}:
            self._reverse_withdrawal(
                reference=paystack_transaction.reference,
                user_id=paystack_transaction.user_id,
                amount=paystack_transaction.amount,
                reason=str(data.get("reason") or "Transfer failed"),
            )
