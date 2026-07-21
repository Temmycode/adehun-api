from dataclasses import dataclass

from pydantic import BaseModel

from app.schemas.participant_schema import ParticipantResponse


@dataclass(frozen=True)
class AssetFile:
    url: str
    type: str
    name: str
    size: float


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
    files: list[AssetFile]
