from pydantic import BaseModel

from app.schemas.user_schema import UserResponse


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse


class LoginRequest(BaseModel):
    id_token: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str
