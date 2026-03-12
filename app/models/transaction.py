from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement import Agreement
    from .agreement_participant import AgreementParticipant


class Transaction(SQLModel, table=True):
    transaction_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    agreement_id: str = Field(foreign_key="agreement.agreement_id")
    participant_id: str = Field(foreign_key="agreement_participant.participant_id")
    condition_id: str | None = None  # INFO: For milestone payment

    amount: Decimal
    type: str = Field(default="deposit")  # Deposit / Withdrawal
    status: str = Field(default="pending")  # pending / accepted / rejected

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None

    agreement: "Agreement" = Relationship(
        back_populates="transactions", sa_relationship_kwargs={"lazy": "selectin"}
    )
    participant: "AgreementParticipant" = Relationship(
        back_populates="transactions", sa_relationship_kwargs={"lazy": "selectin"}
    )
