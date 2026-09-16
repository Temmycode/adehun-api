from datetime import datetime, timezone

from app.common.enums import AgreementStatus, ParticipantRole
from app.exceptions import (
    BadRequestError,
    ConditionNotFoundError,
    ConditionSaveError,
    ForbiddenError,
    ParticipantNotFoundError,
)
from app.logging import get_logger
from app.models import Agreement, AgreementParticipant, Condition, Invitation
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


# Statuses in which the depositor may still decide on a condition.
_DECIDABLE_STATUSES = {"pending", "submitted", "rejected"}


class ConditionService:
    """Conditions are the deliverables that hold the escrow.

    Authority model:
      * either accepted participant may ADD a condition while the agreement is
        still `pending` (before both sides have committed and money moved);
      * only the DEPOSITOR (the payer) may APPROVE or REJECT a condition, and
        only while the agreement is `active` (funded, not disputed). The
        beneficiary fulfils conditions; they never sign off on their own work.
    """

    def __init__(self, condition_repo: ConditionRepository):
        self.condition_repo = condition_repo

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _get_agreement(self, agreement_id: str) -> Agreement | None:
        return self.condition_repo.session.get(Agreement, agreement_id)

    def _require_condition(self, condition_id: str) -> Condition:
        condition = self.condition_repo.get_by_id(condition_id)
        if not condition:
            logger.info("condition not found", extra={"condition_id": condition_id})
            raise ConditionNotFoundError()
        return condition

    def _require_depositor(
        self, condition: Condition, user_id: str
    ) -> AgreementParticipant:
        participant = self.condition_repo.get_participant(
            user_id, condition.agreement_id
        )
        if not participant:
            raise ForbiddenError("You are not a participant in this agreement")
        if participant.role != ParticipantRole.DEPOSITOR:
            logger.warning(
                "non-depositor attempted a condition decision",
                extra={"condition_id": condition.id, "user_id": user_id},
            )
            raise ForbiddenError("Only the depositor can approve or reject conditions")

        agreement = self._get_agreement(condition.agreement_id)
        if agreement is None or agreement.status != AgreementStatus.ACTIVE:
            status = agreement.status if agreement else "missing"
            raise BadRequestError(
                f"Conditions can only be decided while the agreement is active "
                f"(current status: {status})"
            )
        if condition.status not in _DECIDABLE_STATUSES:
            raise BadRequestError(
                f"A condition that is {condition.status} cannot be changed"
            )
        return participant

    def _invalidate(self, agreement_id: str, condition_id: str | None = None) -> None:
        keys = [_agreement_condition(agreement_id)]
        if condition_id:
            keys.append(_condition_key(condition_id))
        self.condition_repo._cache_delete(*keys)

    # ------------------------------------------------------------------ #
    #  Commands                                                           #
    # ------------------------------------------------------------------ #

    def add_condition(
        self, agreement_id: str, user_id: str, condition_data: ConditionCreate
    ) -> ConditionResponse:
        """Add a condition. Allowed for participants while the deal is pending."""
        current_participant = self.condition_repo.get_participant(user_id, agreement_id)
        if not current_participant:
            raise ParticipantNotFoundError()

        agreement = self._get_agreement(agreement_id)
        if agreement is None:
            raise ParticipantNotFoundError()
        if agreement.status != AgreementStatus.PENDING:
            raise BadRequestError(
                "Conditions can only be added before the agreement becomes active"
            )

        other = self.condition_repo.get_participant_or_invitation_by_email(
            str(condition_data.required_from_email), agreement_id
        )
        if not other:
            logger.info(
                "required_from participant/invitation not found",
                extra={"agreement_id": agreement_id},
            )
            raise ParticipantNotFoundError()

        condition = Condition(
            agreement_id=agreement_id,
            participant_id=current_participant.id,
            title=condition_data.title,
            description=condition_data.description,
            required_from_participant_id=(
                other.id if isinstance(other, AgreementParticipant) else None
            ),
            invitation_id=other.id if isinstance(other, Invitation) else None,
        )
        try:
            self.condition_repo.save_condition(condition)
            self._invalidate(agreement_id)
            logger.info(
                "condition created",
                extra={"condition_id": condition.id, "agreement_id": agreement_id},
            )
            return ConditionResponse.model_validate(
                self.condition_repo.get_by_id(condition.id)
            )
        except Exception as e:
            self.condition_repo.rollback()
            logger.exception(
                "failed to save condition",
                extra={"agreement_id": agreement_id, "user_id": user_id},
            )
            raise ConditionSaveError() from e

    def approve_condition(self, condition_id: str, user_id: str) -> ConditionResponse:
        condition = self._require_condition(condition_id)
        self._require_depositor(condition, user_id)

        condition.approved_at = datetime.now(timezone.utc)
        condition.rejected_reason = None
        condition.status = "approved"
        self.condition_repo.save_condition(condition)
        self._invalidate(condition.agreement_id, condition_id)

        logger.info(
            "condition approved", extra={"condition_id": condition_id, "user_id": user_id}
        )
        return ConditionResponse.model_validate(condition)

    def reject_condition(
        self, condition_id: str, user_id: str, rejected_reason: str
    ) -> ConditionResponse:
        condition = self._require_condition(condition_id)
        self._require_depositor(condition, user_id)

        condition.rejected_reason = rejected_reason
        condition.approved_at = None
        condition.status = "rejected"
        self.condition_repo.save_condition(condition)
        self._invalidate(condition.agreement_id, condition_id)

        logger.info(
            "condition rejected", extra={"condition_id": condition_id, "user_id": user_id}
        )
        return ConditionResponse.model_validate(condition)

    # ------------------------------------------------------------------ #
    #  Queries                                                            #
    # ------------------------------------------------------------------ #

    def get_condition(self, condition_id: str) -> ConditionResponse:
        return ConditionResponse.model_validate(self._require_condition(condition_id))

    def get_agreement_id_for_condition(self, condition_id: str) -> str:
        return self._require_condition(condition_id).agreement_id

    def get_agreement_conditions(
        self, agreement_id: str, user_id: str
    ) -> list[BatchConditionResponse]:
        conditions = self.condition_repo.get_agreement_condition(agreement_id, user_id)
        return [BatchConditionResponse.model_validate(c) for c in conditions]

    def all_conditions_approved(self, agreement_id: str, user_id: str) -> bool:
        """Whether every condition has been approved.

        An agreement with no conditions never auto-releases: there would be
        nothing holding the money, and releasing on that basis is a surprise.
        """
        conditions = self.condition_repo.get_agreement_condition(agreement_id, user_id)
        if not conditions:
            return False
        return all(condition.status == "approved" for condition in conditions)

    def get_user_conditions(self, user_id: str) -> list[BatchConditionResponse]:
        return [
            BatchConditionResponse.model_validate(condition)
            for condition in self.condition_repo.get_user_conditions(user_id)
        ]
