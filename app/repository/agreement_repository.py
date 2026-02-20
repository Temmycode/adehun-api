import logging

from redis import Redis
from sqlmodel import Session, select

from app.models import Agreement, AgreementParticipant
from app.redis import RedisClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_LIST = 60 * 5  # 5 min   – list/collection keys
_TTL_USER_AGREEMENTS = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_AGREEMENTS = 60 * 60 * 24  # 24 hours – cache TTL
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agreement_key(agreement_id: str) -> str:
    return f"agreement:{agreement_id}"


def _agreement_participant_key(agreement_id: str, participant_id: str) -> str:
    return f"agreement:{agreement_id}:participant:{participant_id}"


def _condition_key(condition_id: str) -> str:
    return f"condition:{condition_id}"


def _user_agreements_key(user_id: str) -> str:
    return f"user:{user_id}:agreements"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class AgreementRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis):
        super().__init__(redis_client)
        self.session = session

    # ------------------------------------------------------------------ #
    #  Agreement Operations                                              #
    # ------------------------------------------------------------------ #

    def add(self, agreement: Agreement) -> Agreement:
        """Add a new item to the database and refresh it."""
        self.session.add(agreement)
        self.session.commit()
        self.session.refresh(agreement)
        return agreement

    def get_user_agreements(self, user_id: str) -> list[Agreement]:
        """Return a list of agreements for the given user ID."""
        key = _user_agreements_key(user_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("Returning agreements for user id=%d", user_id)
            return [Agreement.model_validate(agreement) for agreement in cached]

        agreements = self.session.exec(
            select(Agreement)
            .join(
                AgreementParticipant,
                AgreementParticipant.agreement_id == Agreement.agreement_id,  # pyright: ignore[reportArgumentType]
            )
            .where(AgreementParticipant.user_id == user_id)
        ).all()
        if agreements:
            self._cache_set(
                key,
                [agreement.model_dump(mode="json") for agreement in agreements],
                _TTL_USER_AGREEMENTS,
            )

        return list(agreements)

    def get_by_id(self, agreement_id: str) -> Agreement | None:
        """Return an agreement by its ID."""
        key = _agreement_key(agreement_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("Returning agreement id=%d", agreement_id)
            return Agreement.model_validate(cached)

        agreement = self.session.exec(
            select(Agreement).where(Agreement.agreement_id == agreement_id)
        ).one_or_none()
        if agreement:
            self._cache_set(key, agreement, _TTL_AGREEMENTS)

        return agreement

    # ------------------------------------------------------------------ #
    #  Write operations (always invalidate relevant cache keys)          #
    # ------------------------------------------------------------------ #

    def save_agreement(self, agreement: Agreement, *, commit: bool = True):
        """Add a new agreement to the database."""
        self.session.add(agreement)
        if commit:
            self.session.commit()
            self.session.refresh(agreement)
            self._cache_set(
                _agreement_key(agreement.agreement_id), agreement, _TTL_AGREEMENTS
            )
        return agreement

    def commit(self) -> None:
        """Commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self.session.rollback()

    def refresh(self, agreement: Agreement) -> None:
        """Refresh a student instance from DB and re-cache it."""
        self.session.refresh(agreement)
        key = _agreement_key(agreement.agreement_id)
        self._cache_set(key, agreement, _TTL_AGREEMENTS)
