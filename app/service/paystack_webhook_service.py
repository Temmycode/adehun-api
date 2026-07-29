"""Paystack webhook processing.

Shape of a handler run:
  1. `claim()` the event on its dedupe key. If we did not win the insert, it has
     already been handled — return 200 and stop.
  2. Lock the `paystack_transaction` row (always the FIRST lock — see the
     locking rules in `wallet_repository`).
  3. Mutate that row in memory WITHOUT committing.
  4. Call `apply_entry`, which commits the ledger row, the balance change and
     the dirty `paystack_transaction` together, in one DB transaction, because
     every repository in a request shares one Session.

Notifications and websocket pushes are returned as *intents* rather than sent
from here: cross-feature orchestration belongs at the router, per CLAUDE.md.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.common.enums import (
    LedgerEntryStatus,
    LedgerEntryType,
    NotificationType,
    WebhookEventStatus,
)
from app.exceptions import AppError
from app.logging import get_logger
from app.models.paystack_transaction import TransactionStatus
from app.repository.wallet_repository import WalletRepository
from app.repository.webhook_event_repository import WebhookEventRepository

logger = get_logger(__name__)


@dataclass
class NotificationIntent:
    user_id: str
    type: NotificationType
    title: str
    message: str
    metadata: dict[str, Any] | None = None

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "metadata": self.metadata,
        }


@dataclass
class WsEvent:
    user_id: str
    payload: dict[str, Any]


@dataclass
class WebhookOutcome:
    http_status: int
    status: str
    event_type: str = ""
    notifications: list[NotificationIntent] = field(default_factory=list)
    ws_events: list[WsEvent] = field(default_factory=list)


def build_dedupe_key(event_type: str, data: dict, raw_body: bytes) -> str:
    """Paystack sends no top-level event id, so `data.id` is the best natural key.

    Namespaced per event type because a charge id and a transfer id can collide
    numerically.
    """
    identifier = (
        data.get("id")
        or data.get("reference")
        or hashlib.sha256(raw_body).hexdigest()
    )
    return f"paystack:{event_type}:{identifier}"[:200]


class PaystackWebhookService:
    def __init__(
        self,
        wallet_repo: WalletRepository,
        webhook_repo: WebhookEventRepository,
    ):
        self.wallet_repo = wallet_repo
        self.webhook_repo = webhook_repo

    async def handle(self, payload: dict, raw_body: bytes) -> WebhookOutcome:
        event_type = str(payload.get("event") or "")
        data = payload.get("data") or {}
        dedupe_key = build_dedupe_key(event_type, data, raw_body)

        claimed = self.webhook_repo.claim(
            dedupe_key=dedupe_key,
            event_type=event_type,
            payload=payload,
            provider_event_id=str(data.get("id")) if data.get("id") else None,
            reference=data.get("reference"),
        )
        if not claimed:
            return WebhookOutcome(200, "duplicate", event_type)

        handler = {
            "charge.success": self._handle_charge_success,
            "transfer.success": self._handle_transfer_success,
            "transfer.failed": self._handle_transfer_failed,
            "transfer.reversed": self._handle_transfer_reversed,
        }.get(event_type)

        if handler is None:
            self.webhook_repo.mark(dedupe_key, WebhookEventStatus.IGNORED)
            return WebhookOutcome(200, "ignored", event_type)

        try:
            outcome = await handler(payload, data)
        except AppError as err:
            self.webhook_repo.mark_failed(dedupe_key, f"{err.code}: {err.message}")
            logger.error(
                "webhook handler rejected the event",
                extra={"event_type": event_type, "code": err.code},
            )
            # A 4xx is our data being wrong; retrying will not help, so ack it.
            # A 5xx is worth another delivery.
            return WebhookOutcome(
                200 if err.status_code < 500 else 500, "failed", event_type
            )
        except Exception as err:
            self.webhook_repo.mark_failed(dedupe_key, repr(err)[:1000])
            logger.exception(
                "webhook handler crashed", extra={"event_type": event_type}
            )
            return WebhookOutcome(500, "error", event_type)

        self.webhook_repo.mark(dedupe_key, WebhookEventStatus.PROCESSED)
        return outcome

    # ------------------------------------------------------------------ #
    #  charge.success                                                    #
    # ------------------------------------------------------------------ #

    async def _handle_charge_success(self, payload: dict, data: dict) -> WebhookOutcome:
        reference = data.get("reference")
        if not reference:
            return WebhookOutcome(200, "ignored", "charge.success")

        # First lock taken, before any wallet lock.
        paystack_transaction = self.wallet_repo.get_paystack_transaction(reference)
        if paystack_transaction is None:
            logger.info(
                "charge for an unknown reference",
                extra={"reference": reference},
            )
            return WebhookOutcome(200, "unknown_reference", "charge.success")

        if paystack_transaction.status != TransactionStatus.PENDING:
            return WebhookOutcome(200, "already_processed", "charge.success")

        paid_kobo = data.get("amount")
        if paid_kobo is None:
            logger.error(
                "charge.success carried no amount", extra={"reference": reference}
            )
            return WebhookOutcome(200, "malformed", "charge.success")

        credited = (Decimal(int(paid_kobo)) / 100).quantize(Decimal("0.01"))
        expected = paystack_transaction.amount

        note = None
        if credited < expected:
            # Credit what actually arrived. The money is the customer's; they can
            # top up the difference. Recording FAILED here and crediting nothing
            # would leave them paid-but-empty and needing a manual refund.
            note = (
                f"Underpaid: expected {to_kobo_str(expected)} kobo, "
                f"received {int(paid_kobo)} kobo"
            )
        elif credited > expected:
            note = (
                f"Overpaid: expected {to_kobo_str(expected)} kobo, "
                f"received {int(paid_kobo)} kobo"
            )

        paystack_transaction.amount = credited
        paystack_transaction.status = TransactionStatus.SUCCESS
        paystack_transaction.paystack_id = data.get("id")
        paystack_transaction.payment_channel = data.get("channel")
        paystack_transaction.gateway_response = note or data.get("gateway_response")
        paystack_transaction.raw_webhook_data = payload
        # Deliberately NOT committed — apply_entry below commits it atomically
        # with the ledger row and the balance change.
        self.wallet_repo.save_paystack_transaction(
            paystack_transaction, commit=False
        )

        result = self.wallet_repo.apply_entry(
            user_id=paystack_transaction.user_id,
            entry_type=LedgerEntryType.DEPOSIT,
            amount=credited,
            reference=f"dep_{paystack_transaction.reference}",
            paystack_transaction_id=paystack_transaction.id,
            description="Wallet funding",
            metadata={
                "channel": data.get("channel"),
                "paystack_id": data.get("id"),
                "note": note,
            },
        )

        if note:
            logger.warning(
                "charge amount did not match the recorded amount",
                extra={"reference": reference, "note": note},
            )

        return WebhookOutcome(
            200,
            "processed",
            "charge.success",
            notifications=[
                NotificationIntent(
                    user_id=paystack_transaction.user_id,
                    type=NotificationType.WALLET_CREDITED,
                    title="Wallet Funded",
                    message=f"Your wallet was credited with {credited}",
                    metadata={"reference": reference, "amount": str(credited)},
                )
            ],
            ws_events=[
                WsEvent(
                    user_id=paystack_transaction.user_id,
                    payload={
                        "type": "WALLET_CREDITED",
                        "amount": float(credited),
                        "available_balance": float(result.wallet.available_balance),
                        "escrow_balance": float(result.wallet.escrow_balance),
                        "total_balance": float(
                            result.wallet.available_balance
                            + result.wallet.escrow_balance
                        ),
                    },
                )
            ],
        )

    # ------------------------------------------------------------------ #
    #  transfer.*                                                        #
    # ------------------------------------------------------------------ #

    async def _handle_transfer_success(
        self, payload: dict, data: dict
    ) -> WebhookOutcome:
        reference = data.get("reference")
        if not reference:
            return WebhookOutcome(200, "ignored", "transfer.success")

        paystack_transaction = self.wallet_repo.get_paystack_transaction(reference)
        if paystack_transaction is None:
            return WebhookOutcome(200, "unknown_reference", "transfer.success")
        if paystack_transaction.status != TransactionStatus.PENDING:
            return WebhookOutcome(200, "already_processed", "transfer.success")

        paystack_transaction.status = TransactionStatus.SUCCESS
        paystack_transaction.paystack_id = data.get("id")
        paystack_transaction.transfer_code = data.get("transfer_code")
        paystack_transaction.raw_webhook_data = payload
        self.wallet_repo.save_paystack_transaction(
            paystack_transaction, commit=False
        )

        # No balance change: the debit already happened at request time.
        self.wallet_repo.mark_entry_status(
            f"wd_{reference}",
            LedgerEntryStatus.COMPLETED,
            processed_at=datetime.now(timezone.utc),
        )

        wallet = self.wallet_repo.get_user_wallet(paystack_transaction.user_id)
        return WebhookOutcome(
            200,
            "processed",
            "transfer.success",
            notifications=[
                NotificationIntent(
                    user_id=paystack_transaction.user_id,
                    type=NotificationType.WITHDRAWAL_COMPLETED,
                    title="Withdrawal Sent",
                    message=(
                        f"{paystack_transaction.amount} has been sent to your bank"
                    ),
                    metadata={"reference": reference},
                )
            ],
            ws_events=[
                WsEvent(
                    user_id=paystack_transaction.user_id,
                    payload={
                        "type": "WITHDRAWAL_COMPLETED",
                        "reference": reference,
                        "amount": float(paystack_transaction.amount),
                        "available_balance": float(wallet.available_balance)
                        if wallet
                        else None,
                    },
                )
            ],
        )

    async def _handle_transfer_failed(
        self, payload: dict, data: dict
    ) -> WebhookOutcome:
        return await self._handle_transfer_reversal(
            payload, data, final_status=TransactionStatus.FAILED
        )

    async def _handle_transfer_reversed(
        self, payload: dict, data: dict
    ) -> WebhookOutcome:
        return await self._handle_transfer_reversal(
            payload, data, final_status=TransactionStatus.REFUNDED
        )

    async def _handle_transfer_reversal(
        self, payload: dict, data: dict, *, final_status: TransactionStatus
    ) -> WebhookOutcome:
        """Put the money back.

        The `wdrev_` reference is UNIQUE, so a redelivered `transfer.failed` —
        or a `failed` followed by a `reversed` for the same transfer — can never
        credit twice.
        """
        reference = data.get("reference")
        if not reference:
            return WebhookOutcome(200, "ignored", "transfer.reversal")

        paystack_transaction = self.wallet_repo.get_paystack_transaction(reference)
        if paystack_transaction is None:
            return WebhookOutcome(200, "unknown_reference", "transfer.reversal")

        # A reversal can legitimately arrive AFTER a success; a plain failure
        # cannot.
        allowed = (
            {TransactionStatus.PENDING, TransactionStatus.SUCCESS}
            if final_status is TransactionStatus.REFUNDED
            else {TransactionStatus.PENDING}
        )
        if paystack_transaction.status not in allowed:
            return WebhookOutcome(200, "already_processed", "transfer.reversal")

        reason = str(
            data.get("reason") or data.get("gateway_response") or "Transfer failed"
        )
        paystack_transaction.status = final_status
        paystack_transaction.failure_reason = reason[:255]
        paystack_transaction.raw_webhook_data = payload

        original = self.wallet_repo.get_entry_by_reference(f"wd_{reference}")
        if original is None:
            # Debited-then-crashed, or a transfer we never ledgered. Do NOT
            # invent a credit out of nothing.
            self.wallet_repo.save_paystack_transaction(paystack_transaction)
            logger.error(
                "transfer reversal with no matching ledger entry",
                extra={"reference": reference},
            )
            return WebhookOutcome(200, "no_ledger_entry", "transfer.reversal")

        self.wallet_repo.save_paystack_transaction(
            paystack_transaction, commit=False
        )
        self.wallet_repo.mark_entry_status(
            original.reference, LedgerEntryStatus.REVERSED, commit=False
        )

        result = self.wallet_repo.apply_entry(
            user_id=paystack_transaction.user_id,
            entry_type=LedgerEntryType.WITHDRAWAL_REVERSAL,
            amount=original.amount,
            reference=f"wdrev_{reference}",
            paystack_transaction_id=paystack_transaction.id,
            description="Withdrawal reversed by bank",
            metadata={"reason": reason[:255], "original_entry_id": original.id},
        )

        return WebhookOutcome(
            200,
            "reversed",
            "transfer.reversal",
            notifications=[
                NotificationIntent(
                    user_id=paystack_transaction.user_id,
                    type=NotificationType.WITHDRAWAL_FAILED,
                    title="Withdrawal Failed",
                    message=(
                        f"Your withdrawal of {original.amount} could not be "
                        f"completed and has been returned to your wallet"
                    ),
                    metadata={"reference": reference, "reason": reason[:255]},
                )
            ],
            ws_events=[
                WsEvent(
                    user_id=paystack_transaction.user_id,
                    payload={
                        "type": "WITHDRAWAL_FAILED",
                        "reference": reference,
                        "amount": float(original.amount),
                        "available_balance": float(
                            result.wallet.available_balance
                        ),
                    },
                )
            ],
        )


def to_kobo_str(amount: Decimal) -> str:
    return str(int(amount * 100))
