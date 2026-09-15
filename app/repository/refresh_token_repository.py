from datetime import datetime, timezone

from sqlmodel import Session, select, update

from app.logging import get_logger
from app.models.refresh_token import RefreshToken

logger = get_logger(__name__)


class RefreshTokenRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, jti: str, user_id: str, expires_at: datetime) -> RefreshToken:
        row = RefreshToken(
            jti=jti,
            user_id=user_id,
            issued_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, jti: str) -> RefreshToken | None:
        return self.session.get(RefreshToken, jti)

    def revoke(self, row: RefreshToken, replaced_by: str | None = None) -> None:
        row.revoked_at = datetime.now(timezone.utc)
        row.replaced_by_jti = replaced_by
        self.session.add(row)
        self.session.flush()

    def revoke_all_for_user(self, user_id: str) -> int:
        """Kill every live session for a user. Returns rows affected."""
        now = datetime.now(timezone.utc)
        result = self.session.exec(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)  # pyright: ignore[reportArgumentType]
            .where(RefreshToken.revoked_at.is_(None))  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
            .values(revoked_at=now)
        )
        self.session.flush()
        return result.rowcount  # pyright: ignore[reportAttributeAccessIssue]

    def purge_expired(self) -> int:
        """Housekeeping: drop rows whose expiry has long passed."""
        cutoff = datetime.now(timezone.utc)
        rows = self.session.exec(
            select(RefreshToken).where(RefreshToken.expires_at < cutoff)
        ).all()
        for row in rows:
            self.session.delete(row)
        self.session.flush()
        return len(rows)

    def commit(self) -> None:
        self.session.commit()
