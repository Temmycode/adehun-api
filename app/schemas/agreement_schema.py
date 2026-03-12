from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.user_schema import UserResponse

from ..schemas.conditions_schema import ConditionResponse
from ..schemas.participant_schema import ParticipantResponse
from ..schemas.transactions_schema import TransactionResponse


class AgreementInvitationResponse(BaseModel):
    invitation_id: str
    email: str
    token: str
    role: str
    status: str
    expires_at: datetime


class AgreementCreate(BaseModel):
    # Agreement Participants
    other_participant_email_or_phone: str
    role: str
    # Agreement Data
    title: str
    description: str
    # Transaction Data
    amount: Decimal


class AgreementResponse(BaseModel):
    title: str
    description: str
    status: str
    conditions: list[ConditionResponse]
    participants: list[ParticipantResponse]
    transactions: list[TransactionResponse]
    invitations: list[AgreementInvitationResponse]

    model_config = {"from_attributes": True}


class InvitationResponse(BaseModel):
    invitation_id: str
    email: str
    token: str
    agreement: AgreementResponse
    role: str
    invited_by_user: UserResponse
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}
