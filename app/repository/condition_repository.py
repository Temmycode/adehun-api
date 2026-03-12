import logging

from redis import Redis
from sqlmodel import Session, select

from app.models import Agreement, AgreementParticipant, Condition
from app.redis import RedisClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_LIST = 60 * 5  # 5 min   – list/collection keys
_TTL_AGREEMENT_CONDITIONS = 60 * 60 * 24  # 24 hours – cache TTL
_TTL_CONDITION = 60 * 60 * 24  # 24 hours – cache TTL
_NONE_SENTINEL = "__none__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _condition_key(condition_id: str) -> str:
    return f"condition:{condition_id}"


def _agreement_condition(agreement_id: str) -> str:
    return f"agreement:{agreement_id}:condition"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
class ConditionRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis):
        super().__init__(redis_client)
        self.session = session

    # ------------------------------------------------------------------ #
    #  Condition Operations                                              #
    # ------------------------------------------------------------------ #

    def flush_condition(self, condition: Condition) -> Condition:
        """Add a new item to the database and refresh it."""
        self.session.add(condition)
        self.session.flush()
        return condition

    def get_agreement_condition(self, agreement_id: str) -> list[Condition]:
        """Return a list of agreements for the given user ID."""
        key = _agreement_condition(agreement_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("Returning agreements for user id=%d", agreement_id)
            return [Condition.model_validate(condition) for condition in cached]

        conditions = self.session.exec(
            select(Condition).where(Condition.agreement_id == agreement_id)
        ).all()

        if conditions:
            self._cache_set(
                key,
                [condition.model_dump(mode="json") for condition in conditions],
                _TTL_AGREEMENT_CONDITIONS,
            )

        return list(conditions)

    def get_by_id(self, condition_id: str) -> Condition | None:
        """Return an agreement by its ID."""
        key = _condition_key(condition_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug("Returning agreement id=%d", condition_id)
            return Condition.model_validate(cached)

        condition = self.session.exec(
            select(Condition).where(Condition.condition_id == condition_id)
        ).one_or_none()
        if condition:
            self._cache_set(key, condition, _TTL_CONDITION)

        return condition

    # ------------------------------------------------------------------ #
    #  Write operations (always invalidate relevant cache keys)          #
    # ------------------------------------------------------------------ #

    def save_condition(self, condition: Condition, *, commit: bool = True):
        """Add a new agreement to the database."""
        self.session.add(condition)
        if commit:
            self.session.commit()
            self.session.refresh(condition)
        return condition

    def commit(self) -> None:
        """Commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self.session.rollback()

    def refresh(self, condition: Condition) -> None:
        """Refresh a student instance from DB and re-cache it."""
        self.session.refresh(condition)
        key = _condition_key(condition.condition_id)
        self._cache_set(key, condition, _TTL_CONDITION)
