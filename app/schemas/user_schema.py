from pydantic import BaseModel


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    phone_number: str | None = None
    profile_picture_url: str | None = None

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    name: str | None = None
    profile_picture_url: str | None = None
