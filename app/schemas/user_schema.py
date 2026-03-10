from pydantic import BaseModel


class UserCreateRequest(BaseModel):
    user_id: str
    phone_number: str
    name: str


class UserResponse(UserCreateRequest):
    email: str
    profile_picture_url: str | None = None

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    name: str | None = None
    profile_picture_url: str | None = None
