from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Asset(SQLModel, table=True):
    asset_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    agreement_id: str = Field(foreign_key="agreement.agreement_id")
    user_id: str = Field(foreign_key="user.user_id")
    document_url: str | None = Field(default=None)
    type: str = Field(default="invited")  # Software/Funds/Document
    deposit_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
