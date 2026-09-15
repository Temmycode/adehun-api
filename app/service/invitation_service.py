import json
import secrets
from datetime import datetime, timezone

from redis import Redis
from sqlmodel import Session, select

from app.exceptions import InvitationNotFoundError
from app.models import Invitation

TOKEN_EXPIRY = 60 * 60 * 24 * 7  # 7 days in seconds
TOKEN_PREFIX = "participant_invite:"


def get_invitation_token() -> str:
    """Generate a secure invitation token."""
    return secrets.token_urlsafe(32)


def store_invitation(redis: Redis | None, token: str, data: dict) -> None:
    """Cache an invitation in Redis. The DB row is the source of truth."""
    if redis is None:
        return
    redis.setex(f"{TOKEN_PREFIX}{token}", TOKEN_EXPIRY, json.dumps(data))


def get_invitation(redis: Redis | None, token: str) -> dict | None:
    if redis is None:
        return None
    data = redis.get(f"{TOKEN_PREFIX}{token}")
    if data:
        return json.loads(data)  # pyright: ignore[reportArgumentType]
    return None


def delete_invitation(redis: Redis | None, token: str) -> None:
    if redis is None:
        return
    redis.delete(f"{TOKEN_PREFIX}{token}")


def _parse_expiry(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_live(status: str | None, expires_at: object) -> bool:
    if (status or "pending") != "pending":
        return False
    expiry = _parse_expiry(expires_at)
    return expiry is None or expiry > datetime.now(timezone.utc)


def find_invitation_by_token(session: Session, token: str) -> Invitation | None:
    return session.exec(select(Invitation).where(Invitation.token == token)).first()


def validate_token(redis: Redis | None, token: str, session: Session) -> dict:
    """Resolve an invitation token; Redis is a cache in front of the DB.

    Raises InvitationNotFoundError when the token is unknown, expired, or no
    longer pending.
    """
    cached = get_invitation(redis, token)
    if cached and _is_live(cached.get("status"), cached.get("expires_at")):
        return cached

    invitation = find_invitation_by_token(session, token)
    if invitation is None or not _is_live(invitation.status, invitation.expires_at):
        raise InvitationNotFoundError()

    return {
        "id": invitation.id,
        "email": invitation.email,
        "token": invitation.token,
        "agreement_id": invitation.agreement_id,
        "role": invitation.role,
        "status": invitation.status,
        "expires_at": invitation.expires_at.isoformat(),
    }
