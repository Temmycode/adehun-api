from pydantic import BaseModel

from app.schemas.user_schema import UserResponse


class ParticipantResponse(BaseModel):
    id: str
    agreement_id: str
    role: str
    status: str
    user: UserResponse

    model_config = {"from_attributes": True}
