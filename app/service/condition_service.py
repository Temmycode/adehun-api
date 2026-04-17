from app.logging import get_logger
from datetime import datetime, timezone

from app.exceptions import (
    ConditionNotFoundError,
    ConditionSaveError,
    ForbiddenError,
    ParticipantNotFoundError,
)
from app.models import AgreementParticipant, Condition, Invitation
from app.redis import RedisClient
from app.repository.condition_repository import ConditionRepository
from app.schemas.conditions_schema import (
    BatchConditionResponse,
    ConditionCreate,
    ConditionResponse,
)

logger = get_logger(__name__)


def _agreement_condition(agreement_id: str) -> str:
    return f"agreement:{agreement_id}:condition"


def _condition_key(condition_id: str) -> str:
    return f"condition:{condition_id}"


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
            logger.error(
                "participant not found when adding condition",
                extra={"user_id": user_id, "agreement_id": agreement_id},
            )
            raise ParticipantNotFoundError()

        other_participant_or_invitation = (
            self.condition_repo.get_participant_or_invitation_by_email(
                condition_data.required_from_email, agreement_id
            )
        )

        if not other_participant_or_invitation:
            logger.error(
                "required_from participant/invitation not found",
                extra={
                    "required_from_email": condition_data.required_from_email,
                    "agreement_id": agreement_id,
                },
            )
            raise ParticipantNotFoundError()

        condition = Condition(
            agreement_id=agreement_id,
            participant_id=current_participant.id,
            **condition_data.model_dump(mode="json"),
            required_from_participant_id=(
                other_participant_or_invitation.id
                if isinstance(other_participant_or_invitation, AgreementParticipant)
                else None
            ),
            invitation_id=(
                other_participant_or_invitation.id
                if isinstance(other_participant_or_invitation, Invitation)
                else None
            ),
        )
        try:
            self.condition_repo.save_condition(condition)

            # Invalidate agreement cache
            self._cache_delete(
                _agreement_condition(agreement_id),
            )
            logger.info(
                "condition created",
                extra={
                    "condition_id": condition.id,
                    "agreement_id": agreement_id,
                    "participant_id": current_participant.id,
                },
            )
            return ConditionResponse.model_validate(
                self.condition_repo.get_by_id(condition.id)
            )
        except Exception as e:
            self.condition_repo.rollback()
            logger.exception(
                "failed to save condition",
                extra={
                    "agreement_id": agreement_id,
                    "user_id": user_id,
                    "error": str(e),
                },
            )
            raise ConditionSaveError() from e

    def approve_condition(self, condition_id: str, user_id: str) -> ConditionResponse:
        """Approve a condition for a given agreement."""
        condition = self.condition_repo.get_by_id(condition_id)
        if not condition:
            logger.error(
                "condition not found for approval",
                extra={"condition_id": condition_id, "user_id": user_id},
            )
            raise ConditionNotFoundError()

        participant = self.condition_repo.get_participant(
            user_id, condition.agreement_id
        )
        if not participant:
            logger.error(
                "participant not found for condition approval",
                extra={"user_id": user_id, "agreement_id": condition.agreement_id},
            )
            raise ParticipantNotFoundError()
        if participant.id != condition.participant_id:
            logger.warning(
                "unauthorized condition approval attempt",
                extra={
                    "condition_id": condition_id,
                    "user_id": user_id,
                    "participant_id": participant.id,
                    "condition_owner_id": condition.participant_id,
                },
            )
            raise ForbiddenError(
                "Only the participant who created the condition can approve it."
            )

        condition.approved_at = datetime.now(timezone.utc)
        condition.status = "approved"
        self.condition_repo.save_condition(condition)

        # Invalidate condition cache
        self._cache_delete(
            _agreement_condition(condition.agreement_id),
            _condition_key(condition_id),
        )
        logger.info(
            "condition approved",
            extra={"condition_id": condition_id, "user_id": user_id},
        )
        return ConditionResponse.model_validate(condition)

    def reject_condition(
        self, condition_id: str, user_id: str, rejected_reason: str
    ) -> ConditionResponse:
        """Reject a condition for a given agreement."""
        condition = self.condition_repo.get_by_id(condition_id)
        if not condition:
            logger.error(
                "condition not found for rejection",
                extra={"condition_id": condition_id, "user_id": user_id},
            )
            raise ConditionNotFoundError()

        participant = self.condition_repo.get_participant(
            user_id, condition.agreement_id
        )
        if not participant:
            logger.error(
                "participant not found for condition rejection",
                extra={"user_id": user_id, "agreement_id": condition.agreement_id},
            )
            raise ParticipantNotFoundError()
        if participant.id != condition.participant_id:
            logger.warning(
                "unauthorized condition rejection attempt",
                extra={
                    "condition_id": condition_id,
                    "user_id": user_id,
                    "participant_id": participant.id,
                    "condition_owner_id": condition.participant_id,
                },
            )
            raise ForbiddenError(
                "Only the participant who created the condition can approve it."
            )

        condition.rejected_reason = rejected_reason
        condition.status = "rejected"
        self.condition_repo.save_condition(condition)

        # Invalidate agreement cache
        self.condition_repo._cache_delete(
            _agreement_condition(condition.agreement_id),
            _condition_key(condition_id),
        )
        logger.info(
            "condition rejected",
            extra={
                "condition_id": condition_id,
                "user_id": user_id,
                "reason": rejected_reason,
            },
        )
        return ConditionResponse.model_validate(condition)

    def get_condition(self, condition_id: str) -> ConditionResponse:
        db_condition = self.condition_repo.get_by_id(condition_id)

        if not db_condition:
            logger.error(
                "condition not found",
                extra={"condition_id": condition_id},
            )
            raise ConditionNotFoundError()

        return ConditionResponse.model_validate(db_condition)

    def get_agreement_conditions(
        self, agreement_ids: list[str], user_id: str
    ) -> list[BatchConditionResponse]:
        conditions = self.condition_repo.get_agreement_condition(agreement_ids, user_id)

        return [
            BatchConditionResponse.model_validate(condition) for condition in conditions
        ]

    def get_user_conditions(self, user_id: str) -> list[BatchConditionResponse]:
        return [
            BatchConditionResponse.model_validate(condition)
            for condition in self.condition_repo.get_user_conditions(user_id)
        ]
