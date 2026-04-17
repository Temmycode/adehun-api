from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement import Agreement
    from .agreement_participant import AgreementParticipant
    from .invitation import Invitation
    from .notification import Notification


class User(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    email: str = Field(index=True, unique=True, nullable=False)
    phone_number: str | None = Field(index=True, nullable=True)
    name: str
    profile_picture_url: str | None = None
    active: int = Field(default=1, nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    participations: list["AgreementParticipant"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"lazy": "selectin"}
    )
    invitations: list["Invitation"] = Relationship(
        back_populates="invited_by_user", sa_relationship_kwargs={"lazy": "selectin"}
    )
    agreements: list["Agreement"] = Relationship(back_populates="user")
    notifications: list["Notification"] = Relationship(back_populates="user")
