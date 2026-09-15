from pydantic import BaseModel, Field, field_validator

from app.core.validators import validate_cloudinary_url

PHONE_PATTERN = r"^\+?[0-9]{7,15}$"


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    phone_number: str | None = None
    profile_picture_url: str | None = None
    # Lets the client decide whether to surface the admin dispute console.
    is_admin: bool = False

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    """PATCH body for the caller's own profile. Omitted fields are untouched."""

    name: str | None = Field(default=None, min_length=2, max_length=80)
    phone_number: str | None = Field(default=None, pattern=PHONE_PATTERN)
    profile_picture_url: str | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value else value

    @field_validator("phone_number", mode="before")
    @classmethod
    def _clean_phone(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return "".join(ch for ch in value.strip() if ch not in " -()")
        return value

    @field_validator("profile_picture_url")
    @classmethod
    def _cloudinary_only(cls, value: str | None) -> str | None:
        return validate_cloudinary_url(value) if value else value
