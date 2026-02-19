from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class AgreementParticipant(SQLModel, table=True):
    participant_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    agreement_id: str = Field(foreign_key="agreement.agreement_id")
    user_id: str = Field(foreign_key="user.user_id")
    role: str = Field(default="beneficiary")  # Depositor/Beneficiary
    status: str = Field(default="invited")  # Invited/Accepted/Rejected
    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
