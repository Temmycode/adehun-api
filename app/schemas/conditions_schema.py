from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.schemas.invitation_schema import ConditionInvitationResponse

from ..schemas.asset_schema import AssetResponse
from ..schemas.participant_schema import ParticipantResponse


class ConditionCreate(BaseModel):
    title: str
    description: str
    required_from_email: EmailStr


class ConditionResponse(BaseModel):
    condition_id: str
    title: str
    description: str
    status: str
    created_by_participant: ParticipantResponse
    required_from_participant: ParticipantResponse | None
    invitation: ConditionInvitationResponse | None
    assets: list[AssetResponse]
    approved_at: datetime | None = None
    rejected_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConditionReject(BaseModel):
    rejected_reason: str
