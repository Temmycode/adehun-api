from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement import Agreement
    from .user import User


class Invitation(SQLModel):
    invitation_id: str = Field(primary_key=True, default_factory=lambda: str(uuid4()))
    email: str
    token: str
    agreement_id: str = Field(foreign_key="agreement.agreement_id")
    role: str
    invited_by: str = Field(foreign_key="users.user_id")
    status: str | None = Field(default="pending")  # pending, accepted, expired
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=7)
    )

    agreement: "Agreement" = Relationship(
        back_populates="invitations", sa_relationship_kwargs={"lazy": "selectin"}
    )
    invited_by_user: "User" = Relationship(
        back_populates="invitations",
        sa_relationship_kwargs={"lazy": "selectin"},
    )
