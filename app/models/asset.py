from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Asset(SQLModel, table=True):
    asset_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    condition_id: str | None = Field(foreign_key="condition.condition_id")
    file_id: str = Field(foreign_key="file.file_id")

    uploaded_by: str = Field(foreign_key="agreement_participant.participant_id")
    is_approved: bool = False

    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
