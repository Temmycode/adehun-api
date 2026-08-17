from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, Index, String, text
from sqlmodel import Field, Relationship, SQLModel

from app.common.enums import DisputeCategory, DisputeResolutionOutcome, DisputeStatus

if TYPE_CHECKING:
    from .agreement import Agreement
    from .asset import Asset
    from .user import User


class Dispute(SQLModel, table=True):
    """A whole-agreement dispute, resolved by a platform admin.

    RECORD-ONLY: resolving a dispute writes an outcome and closes the row. It
    never touches a wallet and never writes a Transaction. Payout and refund
    remain the existing release flow / a deliberate ops action.

    While a dispute is open the agreement sits at `disputed`, which blocks both
    escrow funding and escrow release. Resolution restores the status captured
    in `agreement_status_before`.
    """

    __table_args__ = (
        Index("ix_dispute_agreement_id", "agreement_id"),
        Index("ix_dispute_status", "status"),
        Index("ix_dispute_raised_by_user_id", "raised_by_user_id"),
        Index("ix_dispute_against_user_id", "against_user_id"),
        # At most one live dispute per agreement. DisputeService checks this too
        # so the client gets a 409 rather than a 500 — this index is the
        # race-proof floor under two concurrent submits.
        Index(
            "ux_dispute_one_active_per_agreement",
            "agreement_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'under_review')"),
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    agreement_id: str = Field(foreign_key="agreement.id", nullable=False)

    # User ids, not participant ids: every consumer downstream (authorisation
    # scoping, notifications, websocket delivery) keys on user id, and
    # `resolved_by_user_id` *cannot* be a participant because the admin is not
    # one. Role is recoverable via the (agreement_id, user_id) unique
    # constraint on agreement_participant.
    raised_by_user_id: str = Field(foreign_key="user.id", nullable=False)
    # The respondent. Derivable from the participant rows, but stored so the
    # admin queue can filter on it with one index scan and so the notification
    # target cannot drift. Always computed server-side, never client-supplied.
    against_user_id: str = Field(foreign_key="user.id", nullable=False)

    category: DisputeCategory = Field(
        sa_column=Column("category", String(32), nullable=False)
    )
    description: str = Field(max_length=2000, nullable=False)

    status: DisputeStatus = Field(
        default=DisputeStatus.OPEN,
        sa_column=Column("status", String(20), nullable=False),
    )

    # The agreement status at the moment the dispute was raised. Resolution
    # restores it. Without this we would have to guess which status to return
    # the agreement to, and a record-only resolution must not guess.
    agreement_status_before: str = Field(max_length=20, nullable=False)

    resolution_outcome: DisputeResolutionOutcome | None = Field(
        default=None,
        sa_column=Column("resolution_outcome", String(32), nullable=True),
    )
    resolution_notes: str | None = Field(default=None, max_length=2000, nullable=True)
    resolved_by_user_id: str | None = Field(
        default=None, foreign_key="user.id", nullable=True
    )
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

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

    # Three FKs point at user.id, so every User relationship needs an explicit
    # `foreign_keys` — without it SQLAlchemy raises AmbiguousForeignKeysError at
    # mapper-configure time, which breaks app startup, not just this feature.
    #
    # These are deliberately one-directional (no back_populates): adding a
    # `disputes` list to Agreement would come back empty whenever
    # AgreementRepository.get_by_id serves from its Redis cache, because the
    # cached instance is transient and its relationships are never loaded.
    agreement: Optional["Agreement"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    raised_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Dispute.raised_by_user_id]",
            "lazy": "selectin",
        }
    )
    against_user: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Dispute.against_user_id]",
            "lazy": "selectin",
        }
    )
    resolved_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Dispute.resolved_by_user_id]",
            "lazy": "selectin",
        }
    )
    evidence: list["Asset"] = Relationship(
        back_populates="dispute", sa_relationship_kwargs={"lazy": "selectin"}
    )
