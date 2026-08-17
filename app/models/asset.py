from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import CheckConstraint, Index
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement_participant import AgreementParticipant
    from .asset_file import AssetFile
    from .condition import Condition
    from .dispute import Dispute


class Asset(SQLModel, table=True):
    __table_args__ = (
        Index("ix_asset_dispute_id", "dispute_id"),
        # An asset has exactly one parent: a condition (a deliverable) or a
        # dispute (supporting evidence). Never both, never neither.
        CheckConstraint(
            "(condition_id IS NOT NULL AND dispute_id IS NULL) "
            "OR (condition_id IS NULL AND dispute_id IS NOT NULL)",
            name="ck_asset_single_parent",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    condition_id: str | None = Field(default=None, foreign_key="condition.id")
    # Dispute evidence. Mutually exclusive with condition_id — see the check
    # constraint above. Note AssetRepository.get_agreement_assets INNER JOINs
    # Condition, so evidence is naturally excluded from the deliverable feeds.
    dispute_id: str | None = Field(default=None, foreign_key="dispute.id")
    file_id: str = Field(foreign_key="asset_file.id")

    uploaded_by: str = Field(foreign_key="agreement_participant.id")
    is_approved: bool = False

    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    condition: Optional["Condition"] = Relationship(
        back_populates="assets", sa_relationship_kwargs={"lazy": "selectin"}
    )
    uploader: "AgreementParticipant" = Relationship(
        back_populates="assets", sa_relationship_kwargs={"lazy": "selectin"}
    )
    file: "AssetFile" = Relationship(
        back_populates="asset", sa_relationship_kwargs={"lazy": "selectin"}
    )
    dispute: Optional["Dispute"] = Relationship(
        back_populates="evidence", sa_relationship_kwargs={"lazy": "selectin"}
    )
