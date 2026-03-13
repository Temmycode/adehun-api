from typing import TYPE_CHECKING
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .asset import Asset


class AssetFile(SQLModel, table=True):
    __tablename__ = "asset_file"  # pyright: ignore[reportAssignmentType]

    file_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    url: str
    type: str  # image/pdf/zip/video/link

    asset: "Asset" = Relationship(
        back_populates="file", sa_relationship_kwargs={"lazy": "selectin"}
    )
