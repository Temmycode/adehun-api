from pydantic import BaseModel

from app.schemas.participant_schema import ParticipantResponse


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
