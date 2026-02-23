from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Condition(SQLModel, table=True):
    condition_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    participant_id: str = Field(foreign_key="agreement_participant.participant_id")

    title: str
    description: str

    required_from_participant_id: str = Field(
        foreign_key="agreement_participant.participant_id"
    )

    status: str = Field(default="pending")
    # pending / submitted / approved / rejected
    approved_at: datetime | None = None
    rejected_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
