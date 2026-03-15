import logging
from datetime import datetime, timezone

from redis import Redis

from app.exceptions import (
    ConditionNotFoundError,
    ConditionSaveError,
    ParticipantNotFoundError,
)
from app.models import AgreementParticipant, Condition, Invitation
from app.redis import RedisClient
from app.repository.condition_repository import ConditionRepository
from app.schemas.conditions_schema import ConditionCreate, ConditionResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ConditionService(RedisClient):
    def __init__(self, condition_repo: ConditionRepository):
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
        try:
            self.condition_repo.save_condition(condition)

            # INFO: Invalidate user cache and agreement cache

            self._cache_delete(
                _agreement_key(agreement_id),
                _user_agreements_key(user_id),
                _agreement_condition(agreement_id),
            )
            return ConditionResponse.model_validate(
                self.condition_repo.get_by_id(agreement_id, condition.condition_id)
            )
        except Exception as e:
            self.condition_repo.rollback()
            logger.exception("Condition save failed: %s", e)
            raise ConditionSaveError() from e

    def approve_condition(
        self, agreement_id: str, condition_id: str, user_id: str
    ) -> ConditionResponse:
        """Approve a condition for a given agreement."""
        condition = self.condition_repo.get_by_id(agreement_id, condition_id)
        if not condition:
            raise ConditionNotFoundError()

        # Ensure the user who is approving is the participant who create the condition
        participant = self.condition_repo.get_participant(user_id, agreement_id)
        if not participant:
            raise ParticipantNotFoundError()
        if participant.participant_id != condition.participant_id:
            raise PermissionError(
                "Only the participant who created the condition can approve it."
            )

        condition.approved_at = datetime.now(timezone.utc)
        condition.status = "approved"
        self.condition_repo.save_condition(condition)

        # INFO: Invalidate agreement cache
        self._cache_delete(
            _user_agreements_key(user_id),
            _agreement_key(agreement_id),
            _agreement_condition(agreement_id),
            _condition_key(condition_id),
        )
        return ConditionResponse.model_validate(condition)

    def reject_condition(
        self, agreement_id: str, condition_id: str, user_id: str, rejected_reason: str
    ) -> ConditionResponse:
        """Reject a condition for a given agreement."""
        condition = self.condition_repo.get_by_id(agreement_id, condition_id)
        if not condition:
            raise ConditionNotFoundError()

        # Ensure the user who is approving is the participant who create the condition
        participant = self.condition_repo.get_participant(user_id, agreement_id)
        if not participant:
            raise ParticipantNotFoundError()
        if participant.participant_id != condition.participant_id:
            raise PermissionError(
                "Only the participant who created the condition can approve it."
            )

        condition.rejected_reason = rejected_reason
        condition.status = "rejected"
        self.condition_repo.save_condition(condition)

        # INFO: Invalidate agreement cache
        self._cache_delete(
            _user_agreements_key(user_id),
            _agreement_key(agreement_id),
            _agreement_condition(agreement_id),
            _condition_key(condition_id),
        )
        return ConditionResponse.model_validate(condition)

    def get_condition(self, agreement_id: str, condition_id: str) -> ConditionResponse:
        db_condition = self.condition_repo.get_by_id(agreement_id, condition_id)

        if not db_condition:
            logger.exception("Condition not found for condition_id=%s", condition_id)
            raise ConditionNotFoundError()

        return ConditionResponse.model_validate(db_condition)

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
