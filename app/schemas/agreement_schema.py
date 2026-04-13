from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.conditions_schema import ConditionCreate, ConditionResponse
from app.schemas.participant_schema import ParticipantResponse
from app.schemas.user_schema import UserResponse


class AgreementInvitationResponse(BaseModel):
    id: str
    email: str
    token: str
    role: str
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}


class AgreementCreate(BaseModel):
    # Agreement Participants
    other_participant_email_or_phone: str
    role: str
    # Agreement Data
    title: str
    description: str
    # Transaction Data
    amount: Decimal
    # Initial conditions
    conditions: list[ConditionCreate]


class AgreementResponse(BaseModel):
    id: str
    title: str
    description: str
    amount: Decimal
    status: str
    depositor: ParticipantResponse | None = None
    beneficiary: ParticipantResponse | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgreementCreateResponse(AgreementResponse):
    conditions: list[ConditionResponse]

    model_config = {"from_attributes": True}


class InvitationResponse(BaseModel):
    id: str
    email: str
    token: str
    agreement: AgreementResponse
    role: str
    invited_by_user: UserResponse
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}


class AgreementStatistics(BaseModel):
    active_agreements: int
    completed_agreements: int
    total_agreements: int
