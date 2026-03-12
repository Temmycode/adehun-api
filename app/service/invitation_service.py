import json
import secrets
from datetime import datetime

from redis import Redis

from app.exceptions import InvitationNotFoundError

TOKEN_EXPIRY = 60 * 60 * 24 * 7  # 7 days in seconds
TOKEN_PREFIX = "participant_invite:"


def get_invitation_token() -> str:
    """Generate a secure invitation token."""
    return secrets.token_urlsafe(32)


def store_invitation(redis: Redis, token: str, data: dict) -> None:
    """Store an invitation token in Redis with participant data."""
    redis.setex(f"{TOKEN_PREFIX}{token}", TOKEN_EXPIRY, json.dumps(data))


def get_invitation(redis: Redis, token: str) -> dict | None:
    """Retrieve an invitation from Redis by token."""
    data = redis.get(f"{TOKEN_PREFIX}{token}")
    if data:
        return json.loads(data)  # pyright: ignore[reportArgumentType]
    return None


def delete_invitation(redis: Redis, token: str) -> None:
    """Delete an invitation from Redis by token."""
    redis.delete(f"{TOKEN_PREFIX}{token}")


def validate_token(redis: Redis, token: str) -> dict:
    """Validate a token exists in Redis."""
    invitation = get_invitation(redis, token)
    if not invitation:
        raise InvitationNotFoundError()

    is_expired = (
        invitation.get("expires_at") and invitation["expires_at"] < datetime.now()
    )

    if is_expired:
        raise InvitationNotFoundError()

    return invitation
