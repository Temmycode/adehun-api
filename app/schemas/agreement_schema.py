from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.user_schema import UserResponse


class AgreementInvitationResponse(BaseModel):
    invitation_id: str
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


class AgreementResponse(BaseModel):
    agreement_id: str
    title: str
    description: str
    amount: Decimal
    status: str
    created_at: datetime

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
