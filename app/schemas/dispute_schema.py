from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.common.enums import DisputeCategory, DisputeResolutionOutcome, DisputeStatus
from app.schemas.asset_schema import AssetFile, AssetResponse
from app.schemas.user_schema import UserResponse


class DisputeCreateRequest(BaseModel):
    """Body of the Raise Dispute screen.

    `files` is the same payload shape the client already posts for condition
    assets: upload direct to Cloudinary with a signature, then send back the
    resulting metadata.
    """

    category: DisputeCategory
    description: str = Field(min_length=20, max_length=2000)
    files: list[AssetFile] = Field(default_factory=list, max_length=10)


class DisputeEvidenceCreateRequest(BaseModel):
    files: list[AssetFile] = Field(min_length=1, max_length=10)


class DisputeResolveRequest(BaseModel):
    outcome: DisputeResolutionOutcome
    resolution_notes: str = Field(min_length=10, max_length=2000)

    @field_validator("outcome")
    @classmethod
    def _supported_outcome(
        cls, value: DisputeResolutionOutcome
    ) -> DisputeResolutionOutcome:
        if value == DisputeResolutionOutcome.SPLIT:
            raise ValueError(
                "Split outcomes are not supported yet; resolve as "
                "favour_depositor or favour_beneficiary"
            )
        return value


class DisputeResponse(BaseModel):
    id: str
    agreement_id: str
    # Denormalised so the dispute list and admin queue need no second fetch.
    agreement_title: str
    agreement_amount: Decimal
    category: DisputeCategory
    description: str
    status: DisputeStatus
    raised_by: UserResponse | None = None
    against_user: UserResponse | None = None
    resolution_outcome: DisputeResolutionOutcome | None = None
    resolution_notes: str | None = None
    resolved_by: UserResponse | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Populated on detail endpoints; empty on list endpoints.
    evidence: list[AssetResponse] = []

    model_config = {"from_attributes": True}


class DisputeListResponse(BaseModel):
    disputes: list[DisputeResponse]
    total: int
