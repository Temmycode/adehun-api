from pydantic import BaseModel


class UserResponse(BaseModel):
    user_id: str
    email: str
    name: str

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    name: str | None = None
    profile_picture_url: str | None = None
