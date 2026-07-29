from enum import StrEnum


class ParticipantRole(StrEnum):
    DEPOSITOR = "depositor"
    BENEFICIARY = "beneficiary"


class InvitationStatus(StrEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class NotificationType(StrEnum):
    INVITATION_RECEIVED = "invitation_received"
    AGREEMENT_ACCEPTED = "agreement_accepted"
    AGREEMENT_DECLINED = "agreement_declined"
    CONDITION_ADDED = "condition_added"
    CONDITION_UPDATED = "condition_updated"
    AGREEMENT_COMPLETED = "agreement_completed"
    ESCROW_FUNDED = "escrow_funded"
    ESCROW_RELEASED = "escrow_released"
    WALLET_CREDITED = "wallet_credited"
    WITHDRAWAL_COMPLETED = "withdrawal_completed"
    WITHDRAWAL_FAILED = "withdrawal_failed"
    GENERAL = "general"


# ---------------------------------------------------------------------------
# Ledger
#
# NOTE: these are persisted in plain String columns via an explicit
# `sa_column=Column(String(n))`. Do NOT let SQLModel infer the column type from
# the StrEnum — it produces a native PG enum that stores member *names*
# ("DEPOSIT") rather than the values below.
# ---------------------------------------------------------------------------


class LedgerEntryType(StrEnum):
    DEPOSIT = "deposit"  # Paystack charge -> available
    ESCROW_LOCK = "escrow_lock"  # available -> escrow (same wallet)
    ESCROW_RELEASE_OUT = "escrow_release_out"  # depositor escrow -> out
    ESCROW_RELEASE_IN = "escrow_release_in"  # -> beneficiary available
    ESCROW_REFUND = "escrow_refund"  # escrow -> available (same wallet)
    WITHDRAWAL = "withdrawal"  # available -> bank
    WITHDRAWAL_REVERSAL = "withdrawal_reversal"  # bank failure -> available
    ADJUSTMENT_CREDIT = "adjustment_credit"  # manual ops
    ADJUSTMENT_DEBIT = "adjustment_debit"


class LedgerDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class LedgerEntryStatus(StrEnum):
    PENDING = "pending"  # money moved, gateway outcome still unknown
    COMPLETED = "completed"
    REVERSED = "reversed"  # superseded by a compensating entry


class WebhookEventStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
