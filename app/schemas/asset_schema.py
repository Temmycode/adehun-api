from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.core.validators import validate_cloudinary_url
from app.schemas.participant_schema import ParticipantResponse

# Mirrors lib/constants/asset_types.dart in the Flutter app. `unknown` is a
# client-side fallback, never something a client should send.
AssetKind = Literal["image", "audio", "video", "pdf", "document", "archive"]


class AssetFile(BaseModel):
    """A file already uploaded to our Cloudinary cloud via a signed upload."""

    url: str
    type: AssetKind
    name: str = Field(min_length=1, max_length=255)
    size: float = Field(gt=0, le=settings.cloudinary_max_file_bytes)

    model_config = {"frozen": True}

    _validate_url = field_validator("url")(validate_cloudinary_url)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return value.strip()


class AssetFileResponse(BaseModel):
    id: str
    url: str
    type: str
    name: str
    size: float

    model_config = {"from_attributes": True}


class AssetResponse(BaseModel):
    id: str
    uploader: ParticipantResponse
    is_approved: bool = False
    file: AssetFileResponse

    model_config = {"from_attributes": True}


class AssetCreateRequest(BaseModel):
    files: list[AssetFile] = Field(min_length=1, max_length=10)
