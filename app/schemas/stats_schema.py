from pydantic import BaseModel


class UserStats(BaseModel):
    """User statistics schema."""

    active_agreements: int
    completed_agreements: int
    total_agreements: int
