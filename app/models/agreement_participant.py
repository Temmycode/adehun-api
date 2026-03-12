from datetime import datetime, timezone
from uuid import uuid4

from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement import Agreement
    from .asset import Asset
    from .condition import Condition
    from .transaction import Transaction
    from .user import User


class AgreementParticipant(SQLModel, table=True):
    participant_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    agreement_id: str = Field(foreign_key="agreement.agreement_id")
    user_id: str = Field(foreign_key="user.user_id")

    role: str = Field(default="beneficiary")  # Depositor / Beneficiary
    status: str = Field(default="invited")  # Invited / Accepted / Rejected

    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    agreement: "Agreement" = Relationship(
        back_populates="participants", sa_relationship_kwargs={"lazy": "selectin"}
    )
    user: "User" = Relationship(
        back_populates="participations", sa_relationship_kwargs={"lazy": "selectin"}
    )
    conditions_created: list["Condition"] = Relationship(
        back_populates="created_by_participant",
        sa_relationship_kwargs={
            "foreign_keys": "[Condition.participant_id]",
            "lazy": "selectin",
        },
    )
    conditions_required: list["Condition"] = Relationship(
        back_populates="required_from_participant",
        sa_relationship_kwargs={
            "foreign_keys": "[Condition.required_from_participant_id]",
            "lazy": "selectin",
        },
    )
    assets: list["Asset"] = Relationship(
        back_populates="uploader", sa_relationship_kwargs={"lazy": "selectin"}
    )
    transactions: list["Transaction"] = Relationship(
        back_populates="participant", sa_relationship_kwargs={"lazy": "selectin"}
    )
