from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .agreement_participant import AgreementParticipant
    from .asset_file import AssetFile
    from .condition import Condition


class Asset(SQLModel, table=True):
    asset_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    condition_id: str | None = Field(default=None, foreign_key="condition.condition_id")
    file_id: str = Field(foreign_key="asset_file.file_id")

    uploaded_by: str = Field(foreign_key="agreement_participant.participant_id")
    is_approved: bool = False

    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    condition: Optional["Condition"] = Relationship(
        back_populates="assets", sa_relationship_kwargs={"lazy": "selectin"}
    )
    uploader: "AgreementParticipant" = Relationship(
        back_populates="assets", sa_relationship_kwargs={"lazy": "selectin"}
    )
    file: "AssetFile" = Relationship(
        back_populates="asset", sa_relationship_kwargs={"lazy": "selectin"}
    )
