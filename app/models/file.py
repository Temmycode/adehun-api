from uuid import uuid4

from sqlmodel import Field, SQLModel


class AssetFile(SQLModel, table=True):
    file_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    asset_id: str = Field(foreign_key="asset.asset_id")
    url: str
    type: str  # image/pdf/zip/video/link
