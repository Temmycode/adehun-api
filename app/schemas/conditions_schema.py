from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.invitation_schema import ConditionInvitationResponse

from ..schemas.participant_schema import ParticipantResponse


class ConditionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    required_from_email: EmailStr

    @field_validator("title", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("required_from_email", mode="after")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class ConditionResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    created_by_participant: ParticipantResponse
    required_from_participant: ParticipantResponse | None
    invitation: ConditionInvitationResponse | None
    approved_at: datetime | None = None
    rejected_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BatchConditionResponse(ConditionResponse):
    agreement_id: str

    model_config = {"from_attributes": True}


class ConditionReject(BaseModel):
    rejected_reason: str = Field(min_length=3, max_length=1000)
