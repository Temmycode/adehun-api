from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.common.enums import AgreementStatus, ParticipantRole
from app.config import settings
from app.core.validators import reject_sub_kobo
from app.schemas.conditions_schema import ConditionCreate, ConditionResponse
from app.schemas.participant_schema import ParticipantResponse
from app.schemas.user_schema import UserResponse


class AgreementInvitationResponse(BaseModel):
    id: str
    email: str
    token: str
    role: str
    # NOTE: this is the INVITATION's status (pending/accepted/expired), not the
    # agreement's, and not AgreementParticipant.status (invited/accepted/rejected).
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}


class AgreementCreate(BaseModel):
    # The field name is historical; only email addresses are accepted. Phone
    # invitations were never deliverable (every lookup downstream is by email).
    other_participant_email_or_phone: EmailStr
    role: ParticipantRole
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    amount: Decimal = Field(gt=0, le=settings.agreement_max_amount)
    conditions: list[ConditionCreate] = Field(default_factory=list, max_length=20)

    _validate_amount = field_validator("amount")(reject_sub_kobo)

    @field_validator("title", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("other_participant_email_or_phone", mode="after")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()

    @property
    def invitee_email(self) -> str:
        return str(self.other_participant_email_or_phone)


class AgreementResponse(BaseModel):
    id: str
    title: str
    description: str
    amount: Decimal
    status: AgreementStatus
    depositor: ParticipantResponse | None = None
    beneficiary: ParticipantResponse | None = None
    created_at: datetime
    condition_count: int | None = 0
    conditions_met_count: int | None = 0
    current_user_accepted: bool = False
    # Derived from the ledger (an `escrow_lock` entry exists), not from a
    # status value — see AgreementService.prepare_escrow_funding.
    is_funded: bool = False

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
