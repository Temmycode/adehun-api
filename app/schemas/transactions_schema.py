from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from ..schemas.participant_schema import ParticipantResponse


class TransactionResponse(BaseModel):
    id: str
    participant: ParticipantResponse
    amount: Decimal
    type: str
    status: str
    processed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
