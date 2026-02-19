from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Condition(SQLModel, table=True):
    condition_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    agreement_id: str = Field(foreign_key="agreement.agreement_id")
    description: str
    trigger_event_status: str = Field(default="not_met")  # Met/NotMet
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
