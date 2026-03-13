from dataclasses import dataclass

from pydantic import BaseModel

from app.schemas.participant_schema import ParticipantResponse


@dataclass
class AssetFile:
    url: str
    type: str


class AssetFileResponse(BaseModel):
    file_id: str
    url: str
    type: str

    model_config = {"from_attributes": True}


class AssetResponse(BaseModel):
    asset_id: str
    uploader: ParticipantResponse
    is_approved: bool = False
    file: AssetFileResponse

    model_config = {"from_attributes": True}


class AssetCreateRequest(BaseModel):
    files: list[AssetFile]
