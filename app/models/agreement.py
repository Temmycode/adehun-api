from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Agreement(SQLModel, table=True):
    agreement_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    description: str
    status: str = Field(default="pending")  # Pending/Active/Disputed/Cancelled/Refunded
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
