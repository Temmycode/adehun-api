import logging

from redis import Redis

from app.exceptions import ConditionNotFoundError, ParticipantNotFoundError
from app.models import AgreementParticipant, Condition, Invitation
from app.redis import RedisClient
from app.repository.condition_repository import ConditionRepository
from app.schemas.conditions_schema import ConditionCreate, ConditionResponse

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
# Service
# ---------------------------------------------------------------------------
class ConditionService(RedisClient):
    def __init__(self, condition_repo: ConditionRepository, redis_client: Redis):
        super().__init__(redis_client)
        self.condition_repo = condition_repo

    def add_condition(
        self, agreement_id: str, user_id: str, condition_data: ConditionCreate
    ) -> ConditionResponse:
        """Add a new condition to an agreement."""

        # get the participant for the user and agreement
        current_participant = self.condition_repo.get_participant(user_id, agreement_id)

        if not current_participant:
            logger.exception(
                "Participant not found for user_id=%s, agreement_id=%s",
                user_id,
                agreement_id,
            )
            raise ParticipantNotFoundError()

        other_participant_or_invitation = (
            self.condition_repo.get_participant_or_invitation_by_email(
                condition_data.required_from_email, agreement_id
            )
        )

        if not other_participant_or_invitation:
            logger.exception(
                "Participant not found for user_id=%s, agreement_id=%s",
                user_id,
                agreement_id,
            )
            raise ParticipantNotFoundError()

        condition = Condition(
            agreement_id=agreement_id,
            participant_id=current_participant.participant_id,
            **condition_data.model_dump(mode="json"),
            required_from_participant_id=other_participant_or_invitation.participant_id
            if isinstance(other_participant_or_invitation, AgreementParticipant)
            else None,
            invitation_id=other_participant_or_invitation.invitation_id
            if isinstance(other_participant_or_invitation, Invitation)
            else None,
        )
        self.condition_repo.save_condition(condition)
        return ConditionResponse.model_validate(condition)

    def get_condition(self, agreement_id: str, condition_id: str) -> ConditionResponse:
        key = _condition_key(condition_id)
        cached = self._cache_get(key)
        if cached is not None:
            return ConditionResponse.model_validate(cached)

        db_condition = self.condition_repo.get_by_id(agreement_id, condition_id)

        if not db_condition:
            logger.exception("Condition not found for condition_id=%s", condition_id)
            raise ConditionNotFoundError()

        condition = ConditionResponse.model_validate(db_condition)
        self._cache_set(key, condition, _TTL_CONDITION)

        return condition

    def get_agreement_conditions(self, agreement_id: str) -> list[ConditionResponse]:
        key = _agreement_condition(agreement_id)
        cached = self._cache_get(key)
        if cached:
            return [ConditionResponse.model_validate(condition) for condition in cached]

        db_conditions = self.condition_repo.get_agreement_condition(agreement_id)
        if not db_conditions:
            logger.exception("Conditions not found for agreement_id=%s", agreement_id)
            raise ConditionNotFoundError()

        conditions = [
            ConditionResponse.model_validate(condition) for condition in db_conditions
        ]
        self._cache_set(
            key,
            [condition.model_dump(mode="json") for condition in conditions],
            _TTL_CONDITION,
        )

        return conditions
