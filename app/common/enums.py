from enum import StrEnum


class ParticipantRole(StrEnum):
    DEPOSITOR = "depositor"
    BENEFICIARY = "beneficiary"


class InvitationStatus(StrEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AgreementStatus(StrEnum):
    """The values actually written to `Agreement.status`.

    NOTE: `Agreement.status` stays a plain `str` column. Annotating the model
    field with this enum would make SQLModel infer a native PG enum that stores
    member *names* — the same trap described in the ledger banner below — and
    forcing an explicit Column(String(20)) would emit a spurious ALTER against a
    live column. Use these members for comparison and assignment only; leave the
    column type alone.
    """

    PENDING = "pending"
    ACTIVE = "active"
    DISPUTED = "disputed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    # Nothing writes this today. Retained because `prepare_escrow_funding`
    # read-guards on it.
    REFUNDED = "refunded"


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
    DISPUTE_RAISED = "dispute_raised"
    DISPUTE_EVIDENCE_ADDED = "dispute_evidence_added"
    DISPUTE_UNDER_REVIEW = "dispute_under_review"
    DISPUTE_RESOLVED = "dispute_resolved"
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


# ---------------------------------------------------------------------------
# Disputes
#
# Same rule as the ledger enums above: these are persisted through an explicit
# `sa_column=Column(String(n))`, never inferred from the StrEnum.
# ---------------------------------------------------------------------------


class DisputeCategory(StrEnum):
    QUALITY_ISSUES = "quality_issues"
    MISSED_DEADLINE = "missed_deadline"
    INCOMPLETE_WORK = "incomplete_work"
    NON_RESPONSIVE = "non_responsive"
    OTHER = "other"


class DisputeStatus(StrEnum):
    OPEN = "open"  # raised, not yet picked up
    UNDER_REVIEW = "under_review"  # an admin has claimed it
    RESOLVED = "resolved"  # terminal — an admin issued a binding outcome


class DisputeResolutionOutcome(StrEnum):
    """Record-only. None of these move money.

    Resolving a dispute writes the outcome and unfreezes the agreement; the
    actual payout or refund remains the existing release flow / a manual ops
    action.
    """

    FAVOUR_DEPOSITOR = "favour_depositor"
    FAVOUR_BENEFICIARY = "favour_beneficiary"
    SPLIT = "split"
    DISMISSED = "dismissed"
