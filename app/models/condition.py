from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement import Agreement
    from .agreement_participant import AgreementParticipant
    from .asset import Asset


class Condition(SQLModel, table=True):
    condition_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    agreement_id: str = Field(foreign_key="agreement.agreement_id")
    participant_id: str = Field(foreign_key="agreement_participant.participant_id")
    # We have this for when the user hasn't accepted an invitation yet
    invitation_id: str | None = Field(
        foreign_key="invitation.invitation_id", default=None
    )

    title: str
    description: str

    required_from_participant_id: str | None = Field(
        foreign_key="agreement_participant.participant_id", default=None
    )

    status: str = Field(default="pending")
    # pending / submitted / approved / rejected
    approved_at: datetime | None = None
    rejected_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    agreement: "Agreement" = Relationship(
        back_populates="conditions", sa_relationship_kwargs={"lazy": "selectin"}
    )
    created_by_participant: "AgreementParticipant" = Relationship(
        back_populates="conditions_created",
        sa_relationship_kwargs={
            "foreign_keys": "[Condition.participant_id]",
            "lazy": "selectin",
        },
    )
    required_from_participant: "AgreementParticipant" = Relationship(
        back_populates="conditions_required",
        sa_relationship_kwargs={
            "foreign_keys": "[Condition.required_from_participant_id]",
            "lazy": "selectin",
        },
    )
    assets: list["Asset"] = Relationship(
        back_populates="condition", sa_relationship_kwargs={"lazy": "selectin"}
    )
