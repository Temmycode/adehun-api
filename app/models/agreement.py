from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement_participant import AgreementParticipant
    from .condition import Condition
    from .invitation import Invitation
    from .transaction import Transaction


class Agreement(SQLModel, table=True):
    agreement_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    description: str
    amount: Decimal
    status: str = Field(
        default="pending"
    )  # Pending/Active/Disputed/Cancelled/Completed/Refunded
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    conditions: list["Condition"] = Relationship(
        back_populates="agreement", sa_relationship_kwargs={"lazy": "selectin"}
    )
    participants: list["AgreementParticipant"] = Relationship(
        back_populates="agreement", sa_relationship_kwargs={"lazy": "selectin"}
    )
    transactions: list["Transaction"] = Relationship(
        back_populates="agreement", sa_relationship_kwargs={"lazy": "selectin"}
    )
    invitations: list["Invitation"] = Relationship(
        back_populates="agreement", sa_relationship_kwargs={"lazy": "selectin"}
    )
