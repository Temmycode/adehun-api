from pydantic import BaseModel, Field, field_validator

from app.schemas.user_schema import UserResponse

# E.164-ish: optional +, 7 to 15 digits. Spaces and dashes are stripped first.
PHONE_PATTERN = r"^\+?[0-9]{7,15}$"


def normalise_phone(value: str) -> str:
    return "".join(ch for ch in value.strip() if ch not in " -()")


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    is_signed_up: bool | None = True
    user: UserResponse


class LoginRequest(BaseModel):
    id_token: str = Field(min_length=1)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserCreateRequest(BaseModel):
    """Complete the profile of the *authenticated* user.

    `user_id` is optional and, when present, must match the bearer token.
    It survives only so older clients that still send it keep working.
    """

    user_id: str | None = None
    phone_number: str = Field(pattern=PHONE_PATTERN)
    name: str = Field(min_length=2, max_length=80)

    @field_validator("phone_number", mode="before")
    @classmethod
    def _clean_phone(cls, value: str) -> str:
        return normalise_phone(value) if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return " ".join(value.split())


class InviteRegisterRequest(BaseModel):
    id_token: str = Field(min_length=1)
    invitation_token: str = Field(min_length=1, max_length=128)
