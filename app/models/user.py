from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    user_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    email: str = Field(index=True, unique=True, nullable=False)
    phone_number: str | None = Field(index=True, nullable=True)
    name: str
    profile_picture_url: str | None = None
    active: int = Field(default=1, nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
