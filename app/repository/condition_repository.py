from app.logging import get_logger

from redis import Redis
from sqlmodel import Session, select

from app.models import Agreement, AgreementParticipant, Condition, Invitation, User
from app.redis import RedisClient

logger = get_logger(__name__)

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


def _agreement_condition(user_id: str) -> str:
    return f"agreement:condition:user:{user_id}"


def _user_conditions(user_id: str) -> str:
    return f"condition:user:{user_id}"


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

    def get_agreement_condition(
        self, agreement_ids: list[str], user_id: str
    ) -> list[Condition]:
        """Return a list of conditions for the given agreement IDs."""
        key = _agreement_condition(user_id)
        cached = self._cache_get(key)
        if cached:
            logger.debug(
                "cache hit for agreement conditions",
                extra={"user_id": user_id, "agreement_ids": agreement_ids},
            )
            return [Condition.model_validate(condition) for condition in cached]

        logger.debug(
            "fetching agreement conditions from db",
            extra={"user_id": user_id, "agreement_ids": agreement_ids},
        )
        db_conditions = self.session.exec(
            select(Condition).where(Condition.agreement_id.in_(agreement_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all()
        conditions = [
            Condition.model_validate(condition) for condition in db_conditions
        ]

        logger.debug(
            "fetched agreement conditions",
            extra={"user_id": user_id, "count": len(conditions)},
        )
        if db_conditions:
            self._cache_set(
                key,
                [condition.model_dump(mode="json") for condition in conditions],
                _TTL_AGREEMENT_CONDITIONS,
            )

        return list(conditions)

    def get_user_conditions(self, user_id: str) -> list[Condition]:
        key = _user_conditions(user_id)
        cached = self._cache_get(key)
        if cached:
            logger.debug("cache hit for user conditions", extra={"user_id": user_id})
            return [Condition.model_validate(condition) for condition in cached]

        logger.debug("fetching user conditions from db", extra={"user_id": user_id})
        conditions = self.session.exec(
            select(Condition)
            .join(Agreement)
            .join(
                AgreementParticipant,
                AgreementParticipant.agreement_id == Agreement.id,  # pyright: ignore[reportArgumentType]
            )
            .where(AgreementParticipant.user_id == user_id)
        ).all()

        self._cache_set(
            key,
            [condition.model_dump(mode="json") for condition in conditions],
            _TTL_CONDITION,
        )
        return list(conditions)

    def get_by_id(self, condition_id: str) -> Condition | None:
        """Return a condition by its ID."""
        key = _condition_key(condition_id)
        cached = self._cache_get(key)
        if cached is not None:
            logger.debug(
                "cache hit for condition", extra={"condition_id": condition_id}
            )
            return Condition.model_validate(cached)

        logger.debug("fetching condition from db", extra={"condition_id": condition_id})
        condition = self.session.get(Condition, condition_id)
        if condition:
            self._cache_set(key, condition, _TTL_CONDITION)
        else:
            logger.info("condition not found", extra={"condition_id": condition_id})
        return condition

    def get_participant(
        self, user_id: str, agreement_id: str
    ) -> AgreementParticipant | None:
        logger.debug(
            "fetching participant",
            extra={"user_id": user_id, "agreement_id": agreement_id},
        )
        participant = self.session.exec(
            select(AgreementParticipant).where(
                AgreementParticipant.user_id == user_id,
                AgreementParticipant.agreement_id == agreement_id,
            )
        ).first()
        if not participant:
            logger.info(
                "participant not found",
                extra={"user_id": user_id, "agreement_id": agreement_id},
            )
        return participant

    def get_participant_or_invitation_by_email(
        self, email: str, agreement_id: str
    ) -> AgreementParticipant | Invitation | None:
        logger.debug(
            "looking up participant or invitation by email",
            extra={"email": email, "agreement_id": agreement_id},
        )
        participant = self.session.exec(
            select(AgreementParticipant)
            .join(User)
            .where(
                User.email == email, AgreementParticipant.agreement_id == agreement_id
            )
        ).first()
        if participant:
            logger.debug(
                "found participant by email",
                extra={"email": email, "participant_id": participant.id},
            )
            return participant
        invitation = self.session.exec(
            select(Invitation).where(
                Invitation.email == email,
                Invitation.agreement_id == agreement_id,
            )
        ).first()
        if invitation:
            logger.debug(
                "found invitation by email",
                extra={"email": email, "invitation_id": invitation.id},
            )
        else:
            logger.info(
                "no participant or invitation found",
                extra={"email": email, "agreement_id": agreement_id},
            )
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
