from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .user import User


class RefreshToken(SQLModel, table=True):
    """One row per issued refresh token, keyed by the JWT `jti`.

    Rotation: presenting a refresh token revokes it (`revoked_at`) and records
    the successor (`replaced_by_jti`). Presenting an already-revoked token is
    treated as theft and revokes every live token for that user.
    """

    __tablename__ = "refresh_token"  # pyright: ignore[reportAssignmentType]

    jti: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True, nullable=False)
    issued_at: datetime = Field(nullable=False)
    expires_at: datetime = Field(nullable=False, index=True)
    revoked_at: datetime | None = Field(default=None, nullable=True)
    replaced_by_jti: str | None = Field(default=None, nullable=True)

    user: "User" = Relationship()
