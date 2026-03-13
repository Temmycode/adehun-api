from datetime import datetime

from pydantic import BaseModel


class ConditionInvitationResponse(BaseModel):
    invitation_id: str
    email: str
    role: str
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}
