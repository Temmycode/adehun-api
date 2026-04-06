import logging

from redis import Redis
from sqlmodel import Session, select

from app.models import AgreementParticipant, Condition, Invitation, User
from app.redis import RedisClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_AGREEMENT_CONDITIONS = 60 * 5  # 5 minutes – cache TTL
_TTL_CONDITION = 60 * 5  # 5 minutes – cache TTL
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
    def __init__(self, session: Session, redis_client: Redis | None):
        self.session = session
        super().__init__(redis_client)

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
        if cached:
            return [Condition.model_validate(condition) for condition in cached]

        db_conditions = self.session.exec(
            select(Condition).where(Condition.agreement_id == agreement_id)
        ).all()
        conditions = [
            Condition.model_validate(condition) for condition in db_conditions
        ]

        if db_conditions:
            self._cache_set(
                key,
                [condition.model_dump(mode="json") for condition in conditions],
                _TTL_AGREEMENT_CONDITIONS,
            )

        return list(conditions)

    def get_by_id(self, agreement_id: str, condition_id: str) -> Condition | None:
        """Return an agreement by its ID."""
        key = _condition_key(condition_id)
        cached = self._cache_get(key)
        if cached is not None:
            return Condition.model_validate(cached)

        condition = self.session.exec(
            select(Condition).where(
                Condition.agreement_id == agreement_id,
                Condition.condition_id == condition_id,
            )
        ).one_or_none()
        self._cache_set(key, condition, _TTL_CONDITION)
        return condition

    def get_participant(
        self, user_id: str, agreement_id: str
    ) -> AgreementParticipant | None:
        return self.session.exec(
            select(AgreementParticipant).where(
                AgreementParticipant.user_id == user_id
                and AgreementParticipant.agreement_id == agreement_id
            )
        ).first()

    def get_participant_or_invitation_by_email(
        self, email: str, agreement_id: str
    ) -> AgreementParticipant | Invitation | None:
        participant = self.session.exec(
            select(AgreementParticipant)
            .join(User)
            .where(
                User.email == email, AgreementParticipant.agreement_id == agreement_id
            )
        ).first()
        if participant:
            return participant
        invitation = self.session.exec(
            select(Invitation).where(
                Invitation.email == email and Invitation.agreement_id == agreement_id
            )
        ).first()
        return invitation

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
